from importlib.util import find_spec
import hashlib
import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.checks import Warning as DjangoWarning
from django.test import SimpleTestCase, TestCase, override_settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from google.genai.errors import APIError
from openai import APIStatusError
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle
from celery.exceptions import Retry
import httpx
from django.utils import timezone
from datetime import timedelta

from apps.intelligence.models import (AIUsageRecord, AnalysisChunkResult, AnalysisIssue,
                                     AnalysisJob, AnalysisSectionResult)
from apps.intelligence.schemas import SectionReviewOutput
from apps.intelligence.services.providers.base import AIProviderError, ProviderResult
from apps.intelligence.services.providers.factory import ai_configuration_error, get_provider
from apps.intelligence.services.providers.gemini_provider import (
    GeminiReviewProvider, GeminiSectionReviewSchema, _validated_review_output,
    gemini_response_json_schema,
)
from apps.intelligence.management.commands.inspect_gemini_schema import inspect_schema_structure
from apps.intelligence.services.providers.openai_provider import OpenAIReviewProvider
from apps.intelligence.services.providers.openai_provider import is_billing_limit_error
from apps.intelligence.services.providers.groq_provider import GroqReviewProvider, groq_response_json_schema
from apps.intelligence.services.review_orchestrator import _fingerprint, _fingerprint_candidates
from apps.intelligence.services.prompts.system import PROMPT_VERSION, SYSTEM_INSTRUCTIONS
from apps.intelligence.tasks import process_analysis_job
from apps.research.models import DocumentVersion, ResearchDocument, ResearchProject
from config.local_environment import load_local_ai_environment
from config.security import security_settings, validate_production_secrets
from apps.intelligence.checks import security_configuration_check

User = get_user_model()


class ProductionSecuritySettingsTests(SimpleTestCase):
    def test_development_http_defaults_remain_unforced(self):
        values = security_settings(debug=True, environ={})
        self.assertFalse(values['SECURE_SSL_REDIRECT'])
        self.assertFalse(values['SESSION_COOKIE_SECURE'])
        self.assertFalse(values['CSRF_COOKIE_SECURE'])
        self.assertEqual(values['SECURE_HSTS_SECONDS'], 0)

    def test_production_defaults_enable_https_cookie_and_hsts_protections(self):
        values = security_settings(debug=False, environ={})
        self.assertTrue(values['SECURE_SSL_REDIRECT'])
        self.assertTrue(values['SESSION_COOKIE_SECURE'])
        self.assertTrue(values['CSRF_COOKIE_SECURE'])
        self.assertEqual(values['SECURE_HSTS_SECONDS'], 31536000)
        self.assertFalse(values['SECURE_HSTS_INCLUDE_SUBDOMAINS'])
        self.assertFalse(values['SECURE_HSTS_PRELOAD'])

    def test_explicit_proxy_aware_overrides_are_respected(self):
        values = security_settings(debug=False, environ={
            'SECURE_SSL_REDIRECT': 'false', 'SESSION_COOKIE_SECURE': 'yes',
            'CSRF_COOKIE_SECURE': '1', 'SECURE_HSTS_SECONDS': '86400',
        })
        self.assertFalse(values['SECURE_SSL_REDIRECT'])
        self.assertTrue(values['SESSION_COOKIE_SECURE'])
        self.assertTrue(values['CSRF_COOKIE_SECURE'])
        self.assertEqual(values['SECURE_HSTS_SECONDS'], 86400)

    def test_secret_validation_fails_closed_without_generating_or_rotating_keys(self):
        validate_production_secrets(True, 'dev', 'dev')
        with self.assertRaises(ImproperlyConfigured):
            validate_production_secrets(False, 'short', 'short')
        existing_secret = 'Existing-django-secret-with-sufficient-entropy-0123456789'
        existing_jwt_key = 'Existing-jwt-secret-with-sufficient-entropy-abcdef012345'
        validate_production_secrets(False, existing_secret, existing_jwt_key)
        self.assertEqual(existing_secret, 'Existing-django-secret-with-sufficient-entropy-0123456789')


class GeminiProviderTests(SimpleTestCase):
    def setUp(self):
        self.payload = {
            'summary': 'The section is clear but would benefit from more methodological detail.',
            'strengths': ['The research question is stated.'],
            'weaknesses': ['Sampling details are incomplete.'],
            'recommendations': ['Describe how participants were selected.'],
            'issues': [{
                'category': 'methodological_detail',
                'severity': 'medium',
                'title': 'Clarify participant selection',
                'explanation': 'The supplied section does not state how participants were selected.',
                'evidence_text': 'Participants were recruited from local clinics.',
                'recommendation': 'Report the actual inclusion and exclusion criteria.',
                'suggested_text': 'Participants were recruited from local clinics using the study criteria.',
            }],
        }

    def _api_error(self, code, status, message):
        return APIError(code, {'error': {'status': status, 'message': message}}, SimpleNamespace(status_code=code))

    @override_settings(GEMINI_API_KEY='test-gemini-key', AI_MODEL='gemini-2.5-flash', AI_REQUEST_TIMEOUT=30,
                       AI_MAX_OUTPUT_TOKENS=512)
    def test_structured_response_and_usage_are_converted_to_shared_provider_result(self):
        from google.genai import types

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(
            text=json.dumps(self.payload),
            usage_metadata=SimpleNamespace(
                prompt_token_count=321, candidates_token_count=87, thoughts_token_count=16,
            ),
            ))),
            close=Mock(),
        )
        with patch('apps.intelligence.services.providers.gemini_provider.genai.Client', return_value=fake_client) as client_factory:
            result = GeminiReviewProvider().review(
                instructions='Review only the supplied section.', content='{"paragraphs": []}', correlation_id='test-job',
            )

        client_factory.assert_called_once()
        args, kwargs = fake_client.models.generate_content.call_args
        self.assertEqual(kwargs['model'], 'gemini-2.5-flash')
        self.assertEqual(kwargs['contents'], '{"paragraphs": []}')
        self.assertEqual(kwargs['config'].system_instruction, 'Review only the supplied section.')
        self.assertEqual(kwargs['config'].response_mime_type, 'application/json')
        self.assertIsNone(kwargs['config'].response_schema)
        self.assertEqual(kwargs['config'].response_json_schema, gemini_response_json_schema())
        self.assertEqual(kwargs['config'].max_output_tokens, 512)
        self.assertEqual(result.output.issues[0].evidence_text, self.payload['issues'][0]['evidence_text'])
        self.assertEqual((result.input_tokens, result.output_tokens, result.reasoning_tokens), (321, 103, 16))
        self.assertTrue(fake_client.close.called)
        self.assertIsInstance(kwargs['config'], types.GenerateContentConfig)

    def test_gemini_schema_avoids_unportable_constraints_and_nullable_unions(self):
        schema = gemini_response_json_schema()
        serialized = json.dumps(schema)
        for unsupported_feature in ('minLength', 'maxLength', 'anyOf', '$defs', '$ref'):
            self.assertNotIn(unsupported_feature, serialized)
        self.assertIn('enum', serialized)
        issue_schema = schema['properties']['issues']['items']
        self.assertIn('severity', issue_schema['required'])
        self.assertIn('suggested_text', issue_schema['required'])
        self.assertEqual(issue_schema['properties']['suggested_text']['type'], 'string')
        self.assertEqual(
            set(schema['required']),
            {'summary', 'strengths', 'weaknesses', 'recommendations', 'issues'},
        )

    def test_offline_schema_report_has_bounded_depth_no_refs_and_no_unknown_keywords(self):
        report = inspect_schema_structure(gemini_response_json_schema())
        self.assertEqual(report['reference_count'], 0)
        self.assertEqual(report['unsupported_keywords'], [])
        self.assertLessEqual(report['maximum_depth'], 8)
        self.assertLess(report['schema_bytes'], 10_000)
        self.assertEqual(report['top_level_fields'], ['issues', 'recommendations', 'strengths', 'summary', 'weaknesses'])

    @override_settings(AI_MODEL='gemini-2.5-flash', AI_MAX_OUTPUT_TOKENS=1024)
    def test_offline_management_command_reports_actual_config_without_provider_secrets(self):
        output = StringIO()
        call_command('inspect_gemini_schema', stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(report['model'], 'gemini-2.5-flash')
        self.assertEqual(report['schema']['reference_count'], 0)
        self.assertEqual(report['schema']['unsupported_keywords'], [])
        self.assertIn('response_json_schema', report['request_config_fields'])
        self.assertIn('system_instruction', report['request_config_fields'])
        self.assertNotIn('api_key', output.getvalue().lower())

    def test_provider_output_converts_optional_writing_suggestion_and_keeps_findings(self):
        provider_payload = {**self.payload, 'issues': [{
            **self.payload['issues'][0], 'suggested_text': '',
        }]}
        result = _validated_review_output(json.dumps(provider_payload))
        issue = result.issues[0]
        self.assertEqual(issue.severity, 'medium')
        self.assertEqual(issue.evidence_text, self.payload['issues'][0]['evidence_text'])
        self.assertEqual(issue.recommendation, self.payload['issues'][0]['recommendation'])
        self.assertIsNone(issue.suggested_text)
        self.assertEqual(result.summary, self.payload['summary'])

    def test_malformed_json_and_schema_mismatch_are_safe_invalid_output_errors(self):
        for text in ('not json', '{"summary":"tiny"}'):
            fake_client = SimpleNamespace(
                models=SimpleNamespace(generate_content=Mock(return_value=SimpleNamespace(text=text))),
                close=Mock(),
            )
            with self.subTest(text=text), patch(
                'apps.intelligence.services.providers.gemini_provider.genai.Client', return_value=fake_client,
            ), self.assertRaises(AIProviderError) as raised:
                GeminiReviewProvider().review(instructions='review', content='{}', correlation_id='test')
            self.assertEqual(raised.exception.category, 'invalid_output')
            self.assertNotIn(text, raised.exception.safe_message)

    def test_api_errors_are_classified_without_exposing_provider_details(self):
        cases = (
            (400, 'INVALID_ARGUMENT', 'Invalid request with private prompt detail', 'provider_invalid_argument', False),
            (400, 'INVALID_ARGUMENT', 'response_schema is invalid', 'provider_schema', False),
            (400, 'INVALID_ARGUMENT', 'Model does not support this generation config', 'provider_model', False),
            (401, 'UNAUTHENTICATED', 'API key not valid', 'provider_authentication', False),
            (403, 'PERMISSION_DENIED', 'Project permission denied', 'provider_authentication', False),
            (402, 'PAYMENT_REQUIRED', 'Prepay credit balance depleted', 'provider_billing', False),
            (403, 'PERMISSION_DENIED', 'Billing account payment required', 'provider_billing', False),
            (404, 'NOT_FOUND', 'Model not found', 'provider_model', False),
            (429, 'RESOURCE_EXHAUSTED', 'Daily quota exceeded', 'provider_quota', False),
            (429, 'RESOURCE_EXHAUSTED', 'You exceeded your current quota', 'provider_quota', False),
            (429, 'RESOURCE_EXHAUSTED', 'Requests per minute rate limit exceeded', 'provider_rate_limit', True),
            (503, 'UNAVAILABLE', 'Service unavailable', 'provider_unavailable', True),
        )
        for code, status_name, detail, expected_category, retryable in cases:
            fake_client = SimpleNamespace(
                models=SimpleNamespace(generate_content=Mock(
                    side_effect=self._api_error(code, status_name, detail),
                )),
                close=Mock(),
            )
            with self.subTest(code=code, detail=detail), patch(
                'apps.intelligence.services.providers.gemini_provider.genai.Client', return_value=fake_client,
            ), self.assertRaises(AIProviderError) as raised:
                GeminiReviewProvider().review(instructions='review', content='{}', correlation_id='test')
            self.assertEqual(raised.exception.category, expected_category)
            self.assertEqual(raised.exception.retryable, retryable)
            self.assertNotIn(detail, raised.exception.safe_message)

    @override_settings(AI_MODEL='gemini-2.5-flash')
    def test_api_error_log_contains_safe_metadata_but_not_provider_message(self):
        secret_detail = 'Invalid request includes private manuscript text and key-like-value'
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(side_effect=self._api_error(400, 'INVALID_ARGUMENT', secret_detail))),
            close=Mock(),
        )
        with patch('apps.intelligence.services.providers.gemini_provider.genai.Client', return_value=fake_client), \
             self.assertLogs('apps.intelligence.services.providers.gemini_provider', level='WARNING') as captured, \
             self.assertRaises(AIProviderError):
            GeminiReviewProvider().review(instructions='private prompt', content='private manuscript', correlation_id='safe-correlation')
        record = captured.records[0]
        self.assertEqual(record.http_status, 400)
        self.assertEqual(record.provider_status, 'invalid_argument')
        self.assertEqual(record.model, 'gemini-2.5-flash')
        self.assertEqual(record.correlation_id, 'safe-correlation')
        self.assertEqual(record.error_category, 'provider_invalid_argument')
        rendered = '\n'.join(captured.output)
        for expected in ('http_status=400', 'provider_status=invalid_argument', 'model=gemini-2.5-flash',
                         'correlation_id=safe-correlation', 'error_category=provider_invalid_argument'):
            self.assertIn(expected, rendered)
        for forbidden in (secret_detail, 'private manuscript', 'private prompt', 'key-like-value'):
            self.assertNotIn(forbidden, rendered)


class GroqProviderTests(SimpleTestCase):
    def setUp(self):
        self.quota_client = Mock()
        self.quota_client.eval.return_value = 1
        self.reserve_patcher = patch(
            'apps.intelligence.services.providers.groq_provider.reserve_request',
            return_value=(self.quota_client, ['rpm', 'rpd', 'tpm', 'tpd', 'observed-tpm', 'observed-rpd', 'tpm-amounts', 'tpd-amounts'], 900, 'reservation-id'),
        )
        self.reserve_mock = self.reserve_patcher.start()
        self.addCleanup(self.reserve_patcher.stop)
        self.payload = {
            'summary': 'The section is clear but would benefit from more methodological detail.',
            'strengths': ['The research question is stated.'],
            'weaknesses': ['Sampling details are incomplete.'],
            'recommendations': ['Describe how participants were selected.'],
            'issues': [{
                'category': 'methodological_detail', 'severity': 'medium',
                'title': 'Clarify participant selection',
                'explanation': 'The supplied section does not state how participants were selected.',
                'evidence_text': 'Participants were recruited from local clinics.',
                'recommendation': 'Report the actual inclusion and exclusion criteria.',
                'suggested_text': None,
            }],
        }

    def _schema_objects(self, node):
        if not isinstance(node, dict):
            return
        if node.get('type') == 'object':
            self.assertFalse(node.get('additionalProperties', True))
            self.assertEqual(set(node.get('required', [])), set(node.get('properties', {})))
            for child in node.get('properties', {}).values():
                self._schema_objects(child)
        if node.get('type') == 'array':
            self._schema_objects(node.get('items'))

    def test_strict_schema_is_closed_required_and_nullable_fields_are_explicit(self):
        schema = groq_response_json_schema()
        encoded = json.dumps(schema)
        for unsupported in ('$defs', '$ref', 'minLength', 'maxLength', 'maxItems', 'anyOf'):
            self.assertNotIn(unsupported, encoded)
        self._schema_objects(schema)
        issue = schema['properties']['issues']['items']
        self.assertEqual(issue['properties']['suggested_text']['type'], ['string', 'null'])
        self.assertEqual(issue['properties']['severity']['enum'], ['critical', 'high', 'medium', 'low', 'informational'])

    @override_settings(GROQ_API_KEY='test-groq-key', AI_MODEL='openai/gpt-oss-20b', AI_REQUEST_TIMEOUT=20,
                       AI_MAX_OUTPUT_TOKENS=700)
    def test_provider_sends_groq_strict_schema_validates_and_records_usage(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.payload)))],
            usage=SimpleNamespace(
                prompt_tokens=123, completion_tokens=45,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=17),
            ),
        )
        raw_response = SimpleNamespace(parse=Mock(return_value=response), headers={
            'x-ratelimit-remaining-tokens': '7000', 'x-ratelimit-reset-tokens': '60s',
        })
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=Mock(return_value=raw_response)))),
            close=Mock(),
        )
        with patch('apps.intelligence.services.providers.groq_provider.OpenAI', return_value=fake_client) as factory, \
             patch('apps.intelligence.services.providers.groq_provider.reconcile_usage') as reconcile:
            result = GroqReviewProvider().review(instructions='Review the supplied text only.', content='Section body.', correlation_id='groq-test')

        factory.assert_called_once_with(
            api_key='test-groq-key', base_url='https://api.groq.com/openai/v1', timeout=20, max_retries=0,
        )
        request = fake_client.chat.completions.with_raw_response.create.call_args.kwargs
        self.assertEqual(request['model'], 'openai/gpt-oss-20b')
        self.assertEqual(request['messages'][0]['content'], 'Review the supplied text only.')
        self.assertEqual(request['messages'][1]['content'], 'Section body.')
        self.assertEqual(request['response_format']['json_schema']['strict'], True)
        self.assertEqual(request['response_format']['json_schema']['schema'], groq_response_json_schema())
        self.assertEqual(request['max_completion_tokens'], 700)
        self.assertEqual(result.output.issues[0].evidence_text, self.payload['issues'][0]['evidence_text'])
        self.assertIsNone(result.output.issues[0].suggested_text)
        self.assertEqual((result.input_tokens, result.output_tokens), (123, 45))
        self.assertEqual(result.reasoning_tokens, 17)
        self.reserve_mock.assert_called_once()
        self.assertGreater(self.reserve_mock.call_args.args[1], 700)
        fake_client.close.assert_called_once()
        self.quota_client.set.assert_called_once()
        self.assertTrue(self.quota_client.set.call_args.args[0].endswith(':observed-tpm'))
        self.assertEqual(self.quota_client.set.call_args.args[1], 7000)
        self.assertEqual(self.quota_client.set.call_args.kwargs['ex'], 60)
        reconcile.assert_called_once_with(self.quota_client, ['rpm', 'rpd', 'tpm', 'tpd', 'observed-tpm', 'observed-rpd', 'tpm-amounts', 'tpd-amounts'], 900, 123, 45, 'reservation-id')
        self.quota_client.close.assert_called_once()

    @override_settings(GROQ_API_KEY='test-groq-key', AI_MODEL='openai/gpt-oss-20b', AI_REQUEST_TIMEOUT=20,
                       AI_MAX_OUTPUT_TOKENS=700)
    def test_malformed_or_invalid_groq_output_fails_server_side_validation(self):
        for text in ('not json', json.dumps({**self.payload, 'issues': [{'severity': 'unknown'}]})):
            fake_client = SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=Mock(return_value=SimpleNamespace(
                    parse=Mock(return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None,
                    )), headers={},
                ))))),
                close=Mock(),
            )
            with self.subTest(response=text), patch(
                'apps.intelligence.services.providers.groq_provider.OpenAI', return_value=fake_client,
            ), self.assertRaises(AIProviderError) as raised:
                GroqReviewProvider().review(instructions='Review.', content='Text.', correlation_id='malformed-test')
            self.assertEqual(raised.exception.category, 'invalid_output')
            self.assertNotIn(text, raised.exception.safe_message)

    @override_settings(GROQ_API_KEY='test-groq-key', AI_MODEL='openai/gpt-oss-20b', AI_REQUEST_TIMEOUT=20,
                       AI_MAX_OUTPUT_TOKENS=700)
    def test_http_errors_are_mapped_and_logs_do_not_include_provider_body(self):
        cases = ((400, 'provider_invalid_argument'), (401, 'provider_authentication'),
                 (402, 'provider_billing'), (403, 'provider_authentication'),
                 (404, 'provider_model'), (413, 'provider_payload_too_large'),
                 (429, 'provider_rate_limit'), (503, 'provider_unavailable'))
        for status_code, expected in cases:
            request = httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')
            response = httpx.Response(status_code, request=request)
            detail = 'sensitive provider response manuscript key material'
            error = APIStatusError(detail, response=response, body={'message': detail})
            fake_client = SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=Mock(side_effect=error)))),
                close=Mock(),
            )
            with self.subTest(status_code=status_code), patch(
                'apps.intelligence.services.providers.groq_provider.OpenAI', return_value=fake_client,
            ), self.assertLogs('apps.intelligence.services.providers.groq_provider', level='WARNING') as captured, \
                    self.assertRaises(AIProviderError) as raised:
                GroqReviewProvider().review(instructions='secret prompt', content='private manuscript', correlation_id='safe-id')
            self.assertEqual(raised.exception.category, expected)
            self.assertNotIn(detail, raised.exception.safe_message)
            rendered = '\n'.join(captured.output)
            self.assertIn(f'http_status={status_code}', rendered)
            self.assertIn('safe-id', rendered)
            self.assertIn(expected, rendered)
            for forbidden in (detail, 'private manuscript', 'secret prompt', 'test-groq-key'):
                self.assertNotIn(forbidden, rendered)

    @override_settings(GROQ_API_KEY='test-groq-key', AI_MODEL='openai/gpt-oss-20b', AI_REQUEST_TIMEOUT=20,
                       AI_MAX_OUTPUT_TOKENS=700)
    def test_429_retry_after_is_preserved_and_headers_are_never_logged(self):
        response = httpx.Response(429, headers={'Retry-After': '27', 'x-ratelimit-remaining-tokens': '0',
                                               'x-ratelimit-reset-tokens': '10s'},
                                  request=httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions'))
        error = APIStatusError('sensitive internal body', response=response, body={'message': 'sensitive internal body'})
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=SimpleNamespace(create=Mock(side_effect=error)))),
            close=Mock(),
        )
        with patch('apps.intelligence.services.providers.groq_provider.OpenAI', return_value=fake_client), \
             patch('apps.intelligence.services.providers.groq_provider.reconcile_usage') as reconcile, \
             self.assertRaises(AIProviderError) as raised:
            GroqReviewProvider().review(instructions='prompt', content='manuscript', correlation_id='safe-id')
        self.assertEqual(raised.exception.category, 'provider_rate_limit')
        self.assertEqual(raised.exception.retry_after_seconds, 27)
        self.assertTrue(raised.exception.retryable)
        reconcile.assert_called_once_with(
            self.quota_client,
            ['rpm', 'rpd', 'tpm', 'tpd', 'observed-tpm', 'observed-rpd', 'tpm-amounts', 'tpd-amounts'],
            900, 0, 0, 'reservation-id',
        )


    def test_local_quota_exhaustion_prevents_provider_request_and_returns_reset_time(self):
        from apps.intelligence.services.providers.groq_quota import reserve_request
        fake_redis = Mock()
        fake_redis.eval.return_value = [0, 43]
        with patch('apps.intelligence.services.providers.groq_quota._client', return_value=fake_redis), \
             override_settings(CELERY_BROKER_URL='redis://localhost:6379/0', GROQ_RPM_LIMIT=30,
                               GROQ_RPD_LIMIT=1000, GROQ_TPM_LIMIT=8000, GROQ_TPD_LIMIT=200000), \
             self.assertRaises(AIProviderError) as raised:
            reserve_request('openai/gpt-oss-20b', 500)
        self.assertEqual(raised.exception.category, 'provider_rate_limit')
        self.assertEqual(raised.exception.retry_after_seconds, 43)
        self.assertTrue(raised.exception.retryable)

    def test_server_quota_headers_parse_reset_durations_without_exposing_values(self):
        from apps.intelligence.services.providers.groq_quota import rate_limit_wait_from_headers
        self.assertEqual(rate_limit_wait_from_headers({'x-ratelimit-remaining-tokens': '0',
                                                       'x-ratelimit-reset-tokens': '2m5.5s'}), 126)
        self.assertEqual(rate_limit_wait_from_headers({'Retry-After': '11'}), 11)

    @override_settings(AI_ANALYSIS_ENABLED=True, AI_PROVIDER='groq', GROQ_API_KEY='test-groq-key',
                       OPENAI_API_KEY='', GEMINI_API_KEY='', AI_MODEL='openai/gpt-oss-20b')
    def test_groq_provider_selection_and_system_check_do_not_require_other_keys(self):
        from apps.intelligence.services.providers.factory import ai_configuration_error, get_provider
        self.assertIsNone(ai_configuration_error())
        self.assertIsInstance(get_provider(), GroqReviewProvider)
        self.assertFalse(any(issue.id == 'intelligence.W001' for issue in security_configuration_check(None)))

    @override_settings(AI_ANALYSIS_ENABLED=True, AI_PROVIDER='groq', GROQ_API_KEY='',
                       OPENAI_API_KEY='unrelated-key', GEMINI_API_KEY='unrelated-key', AI_MODEL='openai/gpt-oss-20b')
    def test_groq_requires_its_own_key(self):
        from apps.intelligence.services.providers.factory import ai_configuration_error
        self.assertIn('Groq API key', ai_configuration_error())
        self.assertTrue(any(isinstance(issue, DjangoWarning) and issue.id == 'intelligence.W001'
                            for issue in security_configuration_check(None)))


class AnalysisAccountingTests(SimpleTestCase):
    def test_openai_response_captures_reasoning_as_a_subset_of_output(self):
        payload = {
            'summary': 'The section is understandable and focused.',
            'strengths': [], 'weaknesses': [], 'recommendations': [], 'issues': [],
        }
        parsed = SectionReviewOutput.model_validate(payload)
        fake_client = SimpleNamespace(
            responses=SimpleNamespace(parse=Mock(return_value=SimpleNamespace(
                output_parsed=parsed,
                usage=SimpleNamespace(
                    input_tokens=25, output_tokens=61,
                    output_tokens_details=SimpleNamespace(reasoning_tokens=19),
                ),
            ))),
            close=Mock(),
        )
        with patch('apps.intelligence.services.providers.openai_provider.OpenAI', return_value=fake_client):
            result = OpenAIReviewProvider().review(
                instructions='Review only supplied text.', content='Manuscript section.', correlation_id='accounting-test',
            )
        self.assertEqual((result.input_tokens, result.output_tokens, result.reasoning_tokens), (25, 61, 19))

    def test_missing_reasoning_breakdown_is_not_falsely_reported_as_zero(self):
        result = ProviderResult(SectionReviewOutput.model_validate({
            'summary': 'The section is understandable and focused.',
            'strengths': [], 'weaknesses': [], 'recommendations': [], 'issues': [],
        }), 10, 20)
        self.assertIsNone(result.reasoning_tokens)

    def test_fingerprint_collapses_whitespace_but_retains_distinct_findings(self):
        first = {'category': 'method', 'title': 'Clarify sample', 'evidence_text': 'participants were selected'}
        spacing_variant = {'category': 'METHOD ', 'title': '  clarify   sample ',
                           'evidence_text': 'participants\n were selected'}
        different = {'category': 'method', 'title': 'Clarify sample size', 'evidence_text': 'participants were selected'}
        self.assertEqual(_fingerprint(first), _fingerprint(spacing_variant))
        self.assertNotEqual(_fingerprint(first), _fingerprint(different))
        old_fingerprint = hashlib.sha256('|'.join(
            str(spacing_variant[key]).casefold().strip()
            for key in ('category', 'title', 'evidence_text')
        ).encode('utf-8')).hexdigest()
        self.assertIn(old_fingerprint, _fingerprint_candidates(spacing_variant))

    def test_prompt_version_and_output_guidance_prioritize_concise_nonredundant_review(self):
        self.assertEqual(PROMPT_VERSION, 'academic-review-v2')
        self.assertIn('avoid padding or repeating points', SYSTEM_INSTRUCTIONS)
        self.assertIn('every distinct material concern', SYSTEM_INSTRUCTIONS)


class GeminiConfigurationTests(SimpleTestCase):
    def test_network_failures_are_retryable_and_safe(self):
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(side_effect=httpx.ConnectError('offline'))),
            close=Mock(),
        )
        with patch('apps.intelligence.services.providers.gemini_provider.genai.Client', return_value=fake_client), \
             self.assertRaises(AIProviderError) as raised:
            GeminiReviewProvider().review(instructions='review', content='{}', correlation_id='test')
        self.assertEqual(raised.exception.category, 'provider_unavailable')
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn('offline', raised.exception.safe_message)

    @override_settings(AI_ANALYSIS_ENABLED=True, AI_PROVIDER='gemini', GEMINI_API_KEY='test-gemini-key',
                       OPENAI_API_KEY='', AI_MODEL='gemini-2.5-flash')
    def test_gemini_selection_does_not_require_an_openai_key(self):
        self.assertIsNone(ai_configuration_error())
        self.assertIsInstance(get_provider(), GeminiReviewProvider)

    @override_settings(AI_ANALYSIS_ENABLED=True, AI_PROVIDER='openai', GEMINI_API_KEY='',
                       OPENAI_API_KEY='test-openai-key', AI_MODEL='gpt-test-model')
    def test_existing_openai_provider_selection_is_preserved(self):
        self.assertIsNone(ai_configuration_error())
        self.assertIsInstance(get_provider(), OpenAIReviewProvider)

    @override_settings(AI_ANALYSIS_ENABLED=True, AI_PROVIDER='gemini', GEMINI_API_KEY='',
                       OPENAI_API_KEY='test-openai-key', AI_MODEL='gemini-2.5-flash')
    def test_gemini_configuration_requires_its_own_key_not_the_openai_key(self):
        self.assertIn('Gemini API key', ai_configuration_error())

    @override_settings(AI_ANALYSIS_ENABLED=True, AI_PROVIDER='gemini', GEMINI_API_KEY='test-gemini-key',
                       OPENAI_API_KEY='', AI_MODEL='gemini-2.5-flash')
    def test_django_system_check_accepts_configured_gemini_without_openai_key(self):
        self.assertFalse(any(issue.id == 'intelligence.W001' for issue in security_configuration_check(None)))

    @override_settings(AI_ANALYSIS_ENABLED=True, AI_PROVIDER='gemini', GEMINI_API_KEY='',
                       AI_MODEL='gemini-2.5-flash')
    def test_django_system_check_warns_when_selected_provider_key_is_missing(self):
        self.assertTrue(any(isinstance(issue, DjangoWarning) and issue.id == 'intelligence.W001'
                            for issue in security_configuration_check(None)))

    def test_windows_local_loader_imports_only_allowlisted_ai_keys(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            env_path = Path(directory) / '.env'
            env_path.write_text(
                'AI_PROVIDER=gemini\nGEMINI_API_KEY=fake-test-key\nAI_MODEL=gemini-2.5-flash\n'
                'GROQ_API_KEY=fake-groq-test-key\nGROQ_MODEL=openai/gpt-oss-20b\n'
                'OPENALEX_API_KEY=fake-openalex-test-key\n'
                'POSTGRES_HOST=db\nREDIS_URL=redis://redis:6379/0\n',
                encoding='utf-8',
            )
            environ = {}
            load_local_ai_environment(environ, env_path, is_windows=True)
        self.assertEqual(environ['AI_PROVIDER'], 'gemini')
        self.assertEqual(environ['AI_MODEL'], 'gemini-2.5-flash')
        self.assertEqual(environ['GROQ_API_KEY'], 'fake-groq-test-key')
        self.assertEqual(environ['GROQ_MODEL'], 'openai/gpt-oss-20b')
        self.assertEqual(environ['OPENALEX_API_KEY'], 'fake-openalex-test-key')
        self.assertNotIn('POSTGRES_HOST', environ)
        self.assertNotIn('REDIS_URL', environ)

    def test_local_loader_preserves_explicit_process_environment_and_is_noop_off_windows(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            env_path = Path(directory) / '.env'
            env_path.write_text('AI_PROVIDER=gemini\nAI_MODEL=gemini-2.5-flash\n', encoding='utf-8')
            environ = {'AI_PROVIDER': 'openai'}
            load_local_ai_environment(environ, env_path, is_windows=True)
            self.assertEqual(environ, {'AI_PROVIDER': 'openai', 'AI_MODEL': 'gemini-2.5-flash'})
            untouched = {}
            load_local_ai_environment(untouched, env_path, is_windows=False)
            self.assertEqual(untouched, {})


class FakeReviewOutput:
    def __init__(self, text):
        self.text = text

    def model_dump(self, mode='json'):
        return {
            'summary': 'The supplied section is understandable, with room to make the study design clearer.',
            'strengths': ['The topic is identified.'],
            'weaknesses': ['The method needs more detail.'],
            'recommendations': ['Describe the selection criteria.'],
            'issues': [{
                'category': 'methodological_detail', 'severity': 'medium',
                'title': 'Clarify the method',
                'explanation': 'The cited sentence does not explain how participants were selected.',
                'evidence_text': self.text,
                'recommendation': 'Add the actual selection criteria used in this study.',
                'suggested_text': 'State the actual criteria used to select the study sample.' if 'selected' in self.text else None,
            }],
        }


class FakeProvider:
    provider_name = 'test-provider'

    def review(self, *, instructions, content, correlation_id):
        import json
        paragraphs = json.loads(content)['paragraphs']
        evidence = paragraphs[0]['text']
        return SimpleNamespace(output=FakeReviewOutput(evidence), input_tokens=20, output_tokens=12, reasoning_tokens=4)


class TemporaryFailureProvider:
    provider_name = 'test-provider'

    def review(self, *, instructions, content, correlation_id):
        raise AIProviderError('provider_unavailable', 'The AI provider is temporarily unavailable.', retryable=True)


class SuccessThenRateLimitProvider:
    provider_name = 'test-provider'

    def __init__(self):
        self.calls = 0

    def review(self, *, instructions, content, correlation_id):
        self.calls += 1
        if self.calls == 2:
            raise AIProviderError('provider_rate_limit', 'Temporary quota wait.', retryable=True,
                                  retry_after_seconds=41)
        return FakeProvider().review(instructions=instructions, content=content, correlation_id=correlation_id)


class PayloadTooLargeOnceProvider:
    provider_name = 'test-provider'

    def __init__(self):
        self.calls = 0

    def review(self, *, instructions, content, correlation_id):
        self.calls += 1
        if self.calls == 1:
            raise AIProviderError('provider_payload_too_large', 'Oversized payload.')
        return FakeProvider().review(instructions=instructions, content=content, correlation_id=correlation_id)


@override_settings(
    AI_ANALYSIS_ENABLED=True, AI_PROVIDER='openai', OPENAI_API_KEY='test-key', AI_MODEL='test-model',
    AI_MAX_DOCUMENT_WORDS=25000, AI_MAX_CHUNK_TOKENS=6000, AI_MAX_RETRIES=2,
    CELERY_TASK_ALWAYS_EAGER=False,
)
class IntelligenceWorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='intelligence-owner', email='owner@example.test', password='StrongPass-987!', is_active=True)
        self.other = User.objects.create_user(username='intelligence-other', email='other@example.test', password='StrongPass-987!', is_active=True)
        self.project = ResearchProject.objects.create(owner=self.owner, title='Water quality study')
        self.document = ResearchDocument.objects.create(project=self.project, owner=self.owner, original_filename='water-study.pdf')
        self.version = DocumentVersion.objects.create(
            document=self.document, revision_number=1, original_filename='water-study.pdf',
            file_extension='.pdf', mime_type='application/pdf', file_size=42, storage_key='test-private-key',
            processing_status=DocumentVersion.ProcessingStatus.COMPLETED,
            extraction_metadata={'sections': [
                {'title': 'Abstract', 'paragraphs': ['This study examines water quality in local wells.']},
                {'title': 'Methodology', 'paragraphs': ['Samples were collected from selected wells.']},
            ]},
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def start(self, **extra):
        payload = {
            'document_id': str(self.document.pk),
            'document_version_id': str(self.version.pk),
            'reviewer_profile': 'general',
            'consent_to_external_processing': True,
            'client_request_id': str(uuid4()),
            **extra,
        }
        return self.client.post('/api/v1/analyses/', payload, format='json')

    def test_analysis_requires_auth_consent_configuration_and_extraction(self):
        anonymous = APIClient().post('/api/v1/analyses/', {}, format='json')
        self.assertEqual(anonymous.status_code, 401)
        with override_settings(AI_ANALYSIS_ENABLED=False):
            unavailable = self.start()
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.data['detail'], 'AI analysis is disabled by server configuration.')
        no_consent = self.start(consent_to_external_processing=False)
        self.assertEqual(no_consent.status_code, 400)
        self.version.processing_status = DocumentVersion.ProcessingStatus.PROCESSING
        self.version.save(update_fields=('processing_status',))
        incomplete = self.start()
        self.assertEqual(incomplete.status_code, 400)

    def test_repeated_history_reads_do_not_consume_analysis_creation_quota(self):
        rates = {'ai_analysis_read': '10/hour', 'ai_analysis': '1/hour'}
        with patch.object(ScopedRateThrottle, 'THROTTLE_RATES', rates):
            for _ in range(6):
                response = self.client.get('/api/v1/analyses/')
                self.assertEqual(response.status_code, 200)
            with patch('apps.intelligence.views.process_analysis_job.delay'):
                response = self.start()
            self.assertEqual(response.status_code, 202)

    def test_analysis_creation_still_uses_its_own_rate_and_returns_retry_after(self):
        rates = {'ai_analysis_read': '120/hour', 'ai_analysis': '1/hour'}
        with patch.object(ScopedRateThrottle, 'THROTTLE_RATES', rates):
            with patch('apps.intelligence.views.process_analysis_job.delay'):
                first = self.start()
                self.assertEqual(first.status_code, 202)
                AnalysisJob.objects.filter(pk=first.data['id']).update(status=AnalysisJob.Status.COMPLETED)
                second = self.start()
            self.assertEqual(second.status_code, 429)
            self.assertIn('throttled', second.data['detail'].lower())
            self.assertTrue(second.get('Retry-After'))

    def test_active_job_limit_returns_a_distinguishable_conflict_reason(self):
        rates = {'ai_analysis_read': '120/hour', 'ai_analysis': '3/hour'}
        with patch.object(ScopedRateThrottle, 'THROTTLE_RATES', rates):
            AnalysisJob.objects.create(
                owner=self.owner, project=self.project, document=self.document, document_version=self.version,
                provider='test-provider', model_identifier='test-model', status=AnalysisJob.Status.QUEUED,
            )
            response = self.start()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['detail'], 'An analysis is already queued or processing for this account.')

    def test_celery_workflow_persists_evidence_sections_and_usage_idempotently(self):
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        self.assertEqual(response.status_code, 202)
        job = AnalysisJob.objects.get(pk=response.data['id'])
        self.assertEqual(job.status, AnalysisJob.Status.COMPLETED)
        self.assertEqual(job.progress, 100)
        self.assertEqual(job.prompt_version, 'academic-review-v2')
        self.assertTrue(job.external_processing_consent)
        self.assertEqual(job.section_results.count(), 2)
        issue = AnalysisIssue.objects.filter(job=job).first()
        source_paragraphs = next(s['paragraphs'] for s in self.version.extraction_metadata['sections'] if s['title'] == issue.section.section_title)
        self.assertIn(issue.evidence_snippet, source_paragraphs[0])
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 2)
        self.assertEqual(list(AIUsageRecord.objects.filter(job=job).values_list('reasoning_tokens', flat=True)), [4, 4])
        detail = self.client.get(f'/api/v1/analyses/{job.pk}/').data
        self.assertEqual(detail['input_tokens'], 40)
        self.assertEqual(detail['output_tokens'], 24)
        self.assertEqual(detail['reasoning_tokens'], 8)
        self.assertEqual(self.client.get(f'/api/v1/analyses/{job.pk}/status/').data['status'], 'completed')
        process_analysis_job.run(str(job.pk))
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 2)
        self.assertEqual(AnalysisIssue.objects.filter(job=job).count(), 2)

    def test_cross_user_cannot_read_jobs_issues_or_documents_analysis(self):
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        job_id = response.data['id']
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'/api/v1/analyses/{job_id}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/analyses/{job_id}/issues/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/documents/{self.document.pk}/analyses/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/analyses/{job_id}/report/').status_code, 404)
        issue = AnalysisIssue.objects.filter(job_id=job_id, writing_suggestion__isnull=False).first()
        original_issue_status = issue.resolution_status
        original_suggestion_status = issue.writing_suggestion.status
        decision = self.client.patch(
            f'/api/v1/analyses/issues/{issue.pk}/', {'suggestion_status': 'accepted'}, format='json',
        )
        self.assertEqual(decision.status_code, 404)
        issue.refresh_from_db()
        issue.writing_suggestion.refresh_from_db()
        self.assertEqual(issue.resolution_status, original_issue_status)
        self.assertEqual(issue.writing_suggestion.status, original_suggestion_status)

    def test_cannot_start_analysis_for_another_users_manuscript(self):
        other_project = ResearchProject.objects.create(owner=self.other, title='Private project')
        other_document = ResearchDocument.objects.create(project=other_project, owner=self.other, original_filename='private.docx')
        other_version = DocumentVersion.objects.create(
            document=other_document, revision_number=1, original_filename='private.docx',
            file_extension='.docx', mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            file_size=12, storage_key='private-test-key', processing_status=DocumentVersion.ProcessingStatus.COMPLETED,
            extraction_metadata={'sections': [{'title': 'Abstract', 'paragraphs': ['Private manuscript text.']}]},
        )
        response = self.start(document_id=str(other_document.pk), document_version_id=str(other_version.pk))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(AnalysisJob.objects.exists())

    def test_provider_billing_limit_is_distinguished_from_transient_rate_limit(self):
        billing_error = SimpleNamespace(body={'error': {'code': 'insufficient_quota', 'type': 'insufficient_quota'}})
        ordinary_limit = SimpleNamespace(body={'error': {'code': 'rate_limit_exceeded', 'type': 'requests'}})
        self.assertTrue(is_billing_limit_error(billing_error))
        self.assertFalse(is_billing_limit_error(ordinary_limit))

    def test_owner_can_cancel_queued_job_and_worker_leaves_it_cancelled(self):
        with patch('apps.intelligence.views.process_analysis_job.delay'):
            response = self.start()
        job_id = response.data['id']
        cancelled = self.client.post(f'/api/v1/analyses/{job_id}/cancel/')
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.data['status'], AnalysisJob.Status.CANCELLED)
        self.assertEqual(process_analysis_job.run(job_id), {'status': AnalysisJob.Status.CANCELLED})
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f'/api/v1/analyses/{job_id}/cancel/').status_code, 404)

    def test_429_keeps_chunk_pending_and_resumes_without_rebilling_completed_chunks(self):
        with patch('apps.intelligence.views.process_analysis_job.delay'):
            response = self.start()
        job_id = response.data['id']
        provider = SuccessThenRateLimitProvider()
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=provider), \
             patch('apps.intelligence.tasks.process_analysis_job.apply_async') as schedule:
            first_run = process_analysis_job.run(job_id)
        job = AnalysisJob.objects.get(pk=job_id)
        self.assertEqual(first_run['status'], AnalysisJob.Status.WAITING_FOR_QUOTA)
        self.assertEqual(job.status, AnalysisJob.Status.WAITING_FOR_QUOTA)
        self.assertGreaterEqual((job.next_attempt_at - timezone.now()).total_seconds(), 41)
        self.assertLess((job.next_attempt_at - timezone.now()).total_seconds(), 47)
        self.assertEqual(job.progress, 50)
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 1)
        states = list(AnalysisChunkResult.objects.filter(job=job).values_list('status', flat=True))
        self.assertEqual(states.count(AnalysisChunkResult.Status.COMPLETED), 1)
        self.assertEqual(states.count(AnalysisChunkResult.Status.QUEUED), 1)
        self.assertNotIn(AnalysisChunkResult.Status.FAILED, states)
        schedule.assert_called_once()

        self.assertEqual(process_analysis_job.run(job_id)['status'], AnalysisJob.Status.WAITING_FOR_QUOTA)
        self.assertEqual(provider.calls, 2, 'A duplicate delivery before ETA must not invoke the provider again.')
        job.next_attempt_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=('next_attempt_at',))
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()):
            resumed = process_analysis_job.run(job_id)
        job.refresh_from_db()
        self.assertEqual(resumed['status'], AnalysisJob.Status.COMPLETED)
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 2)
        self.assertEqual(AnalysisChunkResult.objects.filter(job=job, status=AnalysisChunkResult.Status.COMPLETED).count(), 2)

    def test_worker_restart_reclaims_expired_processing_lease_and_duplicate_active_delivery_is_safe(self):
        with patch('apps.intelligence.views.process_analysis_job.delay'):
            response = self.start()
        job = AnalysisJob.objects.get(pk=response.data['id'])
        job.status = AnalysisJob.Status.PROCESSING
        job.processing_lease_until = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=('status', 'processing_lease_until'))
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()):
            result = process_analysis_job.run(str(job.pk))
        self.assertEqual(result['status'], AnalysisJob.Status.COMPLETED)

        with patch('apps.intelligence.services.review_orchestrator.get_provider') as provider:
            job.status = AnalysisJob.Status.PROCESSING
            job.processing_lease_until = timezone.now() + timedelta(minutes=5)
            job.save(update_fields=('status', 'processing_lease_until'))
            duplicate = process_analysis_job.run(str(job.pk))
        self.assertEqual(duplicate['status'], 'already_processing')
        provider.assert_not_called()

    @override_settings(AI_MAX_CHUNK_TOKENS=6000)
    def test_413_splits_and_persists_range_only_subchunks_then_completes(self):
        self.version.extraction_metadata = {'sections': [
            {'title': 'Abstract', 'paragraphs': ['The method was carefully evaluated. ' * 100]},
        ]}
        self.version.save(update_fields=('extraction_metadata',))
        with patch('apps.intelligence.views.process_analysis_job.delay'):
            response = self.start()
        provider = PayloadTooLargeOnceProvider()
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=provider):
            result = process_analysis_job.run(response.data['id'])
        job = AnalysisJob.objects.get(pk=response.data['id'])
        self.assertEqual(result['status'], AnalysisJob.Status.COMPLETED)
        self.assertEqual(provider.calls, 3)
        self.assertEqual(AnalysisChunkResult.objects.filter(job=job, status=AnalysisChunkResult.Status.SUPERSEDED).count(), 1)
        children = AnalysisChunkResult.objects.filter(job=job, parent_chunk__isnull=False)
        self.assertEqual(children.count(), 2)
        self.assertTrue(all(child.source_ranges for child in children))
        self.assertEqual(AIUsageRecord.objects.filter(job=job).count(), 2)

    def test_owner_can_resume_legacy_partial_job_without_resetting_completed_results(self):
        with patch('apps.intelligence.views.process_analysis_job.delay'):
            started = self.start()
        job = AnalysisJob.objects.get(pk=started.data['id'])
        section = AnalysisSectionResult.objects.create(
            job=job, section_key='resume-test', section_title='Abstract', section_category='abstract',
        )
        completed = AnalysisChunkResult.objects.create(job=job, section=section, chunk_index=0,
                                                        status=AnalysisChunkResult.Status.COMPLETED,
                                                        structured_result={'summary': 'Saved result'})
        failed = AnalysisChunkResult.objects.create(job=job, section=section, chunk_index=1,
            status=AnalysisChunkResult.Status.FAILED, error_category='provider_rate_limit')
        AnalysisChunkResult.objects.create(job=job, section=section, chunk_index=2,
                                           status=AnalysisChunkResult.Status.QUEUED)
        job.status = AnalysisJob.Status.PARTIALLY_COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=('status', 'completed_at'))
        with patch('apps.intelligence.views.process_analysis_job.delay') as enqueue:
            resumed = self.client.post(f'/api/v1/analyses/{job.pk}/resume/', {}, format='json')
        self.assertEqual(resumed.status_code, 202)
        enqueue.assert_called_once_with(str(job.pk))
        completed.refresh_from_db()
        failed.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(completed.status, AnalysisChunkResult.Status.COMPLETED)
        self.assertEqual(failed.status, AnalysisChunkResult.Status.QUEUED)
        self.assertEqual(failed.retry_count, 0)
        self.assertEqual(job.status, AnalysisJob.Status.QUEUED)

    def test_other_user_cannot_resume_analysis(self):
        with patch('apps.intelligence.views.process_analysis_job.delay'):
            started = self.start()
        job = AnalysisJob.objects.get(pk=started.data['id'])
        job.status = AnalysisJob.Status.PARTIALLY_COMPLETED
        job.save(update_fields=('status',))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(f'/api/v1/analyses/{job.pk}/resume/').status_code, 404)

    def test_retryable_provider_failure_requeues_then_can_complete(self):
        with patch('apps.intelligence.views.process_analysis_job.delay'):
            response = self.start()
        job_id = response.data['id']
        with patch('apps.intelligence.tasks.process_analysis_job.apply_async') as schedule:
            with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=TemporaryFailureProvider()):
                result = process_analysis_job.run(job_id)
        schedule.assert_called_once()
        self.assertEqual(result['status'], AnalysisJob.Status.WAITING_FOR_QUOTA)
        job = AnalysisJob.objects.get(pk=job_id)
        self.assertEqual(job.status, AnalysisJob.Status.WAITING_FOR_QUOTA)
        self.assertEqual(job.error_category, 'provider_unavailable')
        self.assertIsNotNone(job.next_attempt_at)
        job.next_attempt_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=('next_attempt_at',))
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()):
            result = process_analysis_job.run(job_id)
        job.refresh_from_db()
        self.assertEqual(result['status'], AnalysisJob.Status.COMPLETED)
        self.assertEqual(job.status, AnalysisJob.Status.COMPLETED)

    def test_gemini_rate_limit_uses_existing_celery_retry_path(self):
        with override_settings(
            AI_PROVIDER='gemini', GEMINI_API_KEY='test-gemini-key', OPENAI_API_KEY='', AI_MODEL='gemini-2.5-flash',
        ):
            with patch('apps.intelligence.views.process_analysis_job.delay'):
                response = self.start()
            self.assertEqual(response.status_code, 202)
            job_id = response.data['id']
            api_error = APIError(
                429,
                {'error': {'status': 'RESOURCE_EXHAUSTED', 'message': 'Requests per minute rate limit exceeded'}},
                SimpleNamespace(status_code=429),
            )
            fake_client = SimpleNamespace(
                models=SimpleNamespace(generate_content=Mock(side_effect=api_error)), close=Mock(),
            )
            with patch('apps.intelligence.tasks.process_analysis_job.apply_async') as schedule, \
                 patch('apps.intelligence.services.providers.gemini_provider.genai.Client', return_value=fake_client), \
                 patch('apps.intelligence.services.review_orchestrator.get_provider') as selected_provider:
                from apps.intelligence.services.providers.gemini_provider import GeminiReviewProvider
                selected_provider.return_value = GeminiReviewProvider()
                task_result = process_analysis_job.run(job_id)
        sent_config = fake_client.models.generate_content.call_args.kwargs['config']
        self.assertIsNone(sent_config.response_schema)
        self.assertEqual(sent_config.response_json_schema, gemini_response_json_schema())
        schedule.assert_called_once()
        job = AnalysisJob.objects.get(pk=job_id)
        self.assertEqual(task_result['status'], AnalysisJob.Status.WAITING_FOR_QUOTA)
        self.assertEqual(job.status, AnalysisJob.Status.WAITING_FOR_QUOTA)
        self.assertEqual(job.error_category, 'provider_rate_limit')

    def test_suggestion_decision_records_choice_without_changing_version(self):
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        job = AnalysisJob.objects.get(pk=response.data['id'])
        issue = AnalysisIssue.objects.filter(job=job, writing_suggestion__isnull=False).first()
        source_snapshot = json.loads(json.dumps(self.version.extraction_metadata))
        suggestion_text = issue.writing_suggestion.suggested_text
        update = self.client.patch(f'/api/v1/analyses/issues/{issue.pk}/', {'suggestion_status': 'accepted'}, format='json')
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.data['resolution_status'], 'accepted')
        issue.refresh_from_db()
        self.assertEqual(issue.writing_suggestion.status, 'accepted')
        self.assertEqual(self.version.processing_status, DocumentVersion.ProcessingStatus.COMPLETED)
        self.version.refresh_from_db()
        self.assertEqual(self.version.extraction_metadata, source_snapshot)
        self.assertEqual(issue.writing_suggestion.suggested_text, suggestion_text)

    def test_rejected_suggestion_can_be_reopened_without_mutating_the_manuscript(self):
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        issue = AnalysisIssue.objects.filter(job_id=response.data['id'], writing_suggestion__isnull=False).first()
        source_snapshot = json.loads(json.dumps(self.version.extraction_metadata))

        rejected = self.client.patch(
            f'/api/v1/analyses/issues/{issue.pk}/', {'suggestion_status': 'rejected'}, format='json',
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.data['resolution_status'], 'rejected')
        issue.refresh_from_db()
        self.assertEqual(issue.writing_suggestion.status, 'rejected')

        reopened = self.client.patch(
            f'/api/v1/analyses/issues/{issue.pk}/', {'suggestion_status': 'proposed'}, format='json',
        )
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.data['resolution_status'], 'open')
        issue.refresh_from_db()
        self.assertEqual(issue.writing_suggestion.status, 'proposed')
        self.version.refresh_from_db()
        self.assertEqual(self.version.extraction_metadata, source_snapshot)

        conflict = self.client.patch(
            f'/api/v1/analyses/issues/{issue.pk}/',
            {'suggestion_status': 'accepted', 'resolution_status': 'rejected'}, format='json',
        )
        self.assertEqual(conflict.status_code, 400)

    def test_provider_failure_is_safe_and_marks_job_failed(self):
        with patch('apps.intelligence.services.review_orchestrator.get_provider', side_effect=AIProviderError('provider_authentication', 'AI provider authentication failed. Check server configuration.')), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        job = AnalysisJob.objects.get(pk=response.data['id'])
        self.assertEqual(job.status, AnalysisJob.Status.FAILED)
        self.assertEqual(job.error_category, 'provider_authentication')
        self.assertNotIn('test-key', job.error_message)

    def test_nonretryable_chunk_failures_are_aggregated_onto_job(self):
        class InvalidRequestProvider:
            provider_name = 'gemini'

            def review(self, *, instructions, content, correlation_id):
                raise AIProviderError(
                    'provider_invalid_argument',
                    'Gemini rejected an analysis request argument. Check model capabilities and request configuration.',
                )

        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=InvalidRequestProvider()), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        job = AnalysisJob.objects.get(pk=response.data['id'])
        self.assertEqual(job.status, AnalysisJob.Status.FAILED)
        self.assertEqual(job.error_category, 'provider_invalid_argument')
        self.assertIn('AI provider rejected an analysis request argument', job.error_message)
        self.assertEqual(job.chunks.filter(status='failed').count(), 2)

    @override_settings(AI_MAX_DOCUMENT_WORDS=2)
    def test_document_limit_fails_without_provider_call(self):
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        job = AnalysisJob.objects.get(pk=response.data['id'])
        self.assertEqual(job.status, AnalysisJob.Status.FAILED)
        self.assertEqual(job.error_category, 'document_limit')

    @staticmethod
    def has_reportlab():
        return find_spec('reportlab') is not None

    def test_report_download_is_private_and_pdf(self):
        if not self.has_reportlab():
            self.skipTest('ReportLab dependency is not installed in this test environment.')
        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=FakeProvider()), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        job_id = response.data['id']
        report = self.client.get(f'/api/v1/analyses/{job_id}/report/')
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report['Content-Type'], 'application/pdf')
        report_bytes = b''.join(report.streaming_content)
        self.assertTrue(report_bytes.startswith(b'%PDF'))
        captured = {}

        class CapturingDocument:
            def __init__(self, *args, **kwargs):
                pass

            def build(self, story):
                captured['story'] = story

        from apps.intelligence.services import report_builder
        with patch.object(report_builder, 'SimpleDocTemplate', CapturingDocument):
            report_builder.build_analysis_report(AnalysisJob.objects.get(pk=job_id))
        def flatten(flowables):
            for flowable in flowables:
                if getattr(flowable, 'text', None):
                    yield flowable.text
                yield from flatten(getattr(flowable, '_content', []))

        report_text = '\n'.join(flatten(captured['story']))
        self.assertIn('Analysis status: Completed', report_text)
        self.assertIn('Revision: 1', report_text)
        self.assertIn('Token usage:', report_text)
        self.assertIn('Decision:</b> open', report_text)
        self.assertNotIn('Â·', report_text)
        self.assertNotIn('â€¢', report_text)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'/api/v1/analyses/{job_id}/report/').status_code, 404)

    def test_cross_paragraph_evidence_is_not_attached_to_a_misleading_single_anchor(self):
        abstract = self.version.extraction_metadata['sections'][0]
        abstract['paragraphs'] = ['The first quoted statement is here.', 'The second quoted statement follows.']
        self.version.save(update_fields=('extraction_metadata',))

        class CrossParagraphEvidenceProvider:
            provider_name = 'test-provider'

            def review(self, *, instructions, content, correlation_id):
                paragraphs = json.loads(content)['paragraphs']
                evidence = '\n'.join(row['text'] for row in paragraphs)
                return SimpleNamespace(output=FakeReviewOutput(evidence), input_tokens=10, output_tokens=5)

        with patch('apps.intelligence.services.review_orchestrator.get_provider', return_value=CrossParagraphEvidenceProvider()), \
             patch('apps.intelligence.views.process_analysis_job.delay', side_effect=lambda job_id: process_analysis_job.run(job_id)):
            response = self.start()
        self.assertEqual(response.status_code, 202)
        self.assertFalse(AnalysisIssue.objects.filter(job_id=response.data['id'], section__section_title='Abstract').exists())
