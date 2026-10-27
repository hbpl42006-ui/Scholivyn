import json
import logging
import re
import time

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ConfigDict, ValidationError
from typing import Literal

from django.conf import settings

from apps.intelligence.schemas import SectionReviewOutput
from .base import AIProviderError, ProviderResult

logger = logging.getLogger(__name__)

# Gemini supports a subset of JSON Schema. `response_json_schema` plus inline
# nested objects avoids passing Pydantic's $defs/$ref encoding through SDK
# schema conversion; the application still validates with SectionReviewOutput.
GEMINI_SCHEMA_KEYWORDS = frozenset({
    '$defs', '$ref', 'type', 'properties', 'required', 'items', 'enum',
    'title', 'description', 'format', 'minimum', 'maximum', 'minItems',
    'maxItems', 'anyOf', 'oneOf', 'additionalProperties',
})


class GeminiReviewIssueSchema(BaseModel):
    model_config = ConfigDict(extra='ignore')

    category: str
    severity: Literal['critical', 'high', 'medium', 'low', 'informational']
    title: str
    explanation: str
    evidence_text: str
    recommendation: str
    # Required plain string for provider compatibility; empty means no edit.
    suggested_text: str


class GeminiSectionReviewSchema(BaseModel):
    model_config = ConfigDict(extra='ignore')

    summary: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    issues: list[GeminiReviewIssueSchema]


def gemini_response_json_schema() -> dict:
    """Return an inline, compact schema suitable for Gemini's JSON mode."""
    schema = GeminiSectionReviewSchema.model_json_schema()
    definitions = schema.pop('$defs', {})

    def inline(node):
        if isinstance(node, list):
            return [inline(item) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get('$ref')
        if ref:
            prefix = '#/$defs/'
            if not ref.startswith(prefix) or ref[len(prefix):] not in definitions:
                raise ValueError('Gemini schema contains an unsupported reference')
            expanded = inline(definitions[ref[len(prefix):]])
            return {**expanded, **{key: inline(value) for key, value in node.items() if key != '$ref'}}
        return {key: inline(value) for key, value in node.items() if key != '$defs'}

    result = inline(schema)
    if result.get('type') != 'object' or result.get('properties', {}).get('issues', {}).get('items', {}).get('type') != 'object':
        raise ValueError('Gemini response schema did not expand to the expected object structure')
    return result


def _validated_review_output(response_text: str) -> SectionReviewOutput:
    provider_output = GeminiSectionReviewSchema.model_validate_json(response_text)
    payload = provider_output.model_dump(mode='python')
    for issue in payload['issues']:
        if issue['suggested_text'] == '':
            issue['suggested_text'] = None
    return SectionReviewOutput.model_validate(payload)


def _classify_api_error(exc: errors.APIError, *, model: str, correlation_id: str) -> AIProviderError:
    code = getattr(exc, 'code', None)
    status_name = str(getattr(exc, 'status', '') or '').casefold()
    # Provider messages are inspected only to choose a safe category. They are
    # never copied into our logs, database errors, or API responses.
    message = str(getattr(exc, 'message', '') or '').casefold()
    detail = f'{status_name} {message}'

    billing_terms = ('billing', 'payment_required', 'payment required', 'prepay', 'spend cap', 'credits depleted')
    if code == 402 or any(term in detail for term in billing_terms):
        classified = AIProviderError(
            'provider_billing',
            'The Gemini project has a billing restriction or depleted credits. Check Google AI Studio billing.',
        )
    elif code == 401 or status_name == 'unauthenticated' or any(
        term in detail for term in ('api key not valid', 'api key invalid', 'api key is invalid',
                                    'invalid api key', 'api_key_invalid', 'authentication')
    ):
        classified = AIProviderError('provider_authentication', 'Gemini authentication failed. Check the server-side API key.')
    elif code == 403:
        classified = AIProviderError(
            'provider_authentication',
            'Gemini access was denied. Check API key permissions and project access.',
        )
    elif code == 404 or any(term in detail for term in ('model not found', 'model_not_found', 'unsupported model')):
        classified = AIProviderError('provider_model', 'The configured Gemini model is unavailable. Check the model identifier.')
    elif code == 429:
        quota_terms = ('daily quota', 'quota_exceeded', 'quota exceeded', 'quota has been exceeded',
                       'current quota', 'quota exhausted', 'exhausted quota', 'per day')
        transient_terms = ('rate', 'per minute', 'per second', 'too many requests')
        if any(term in detail for term in quota_terms) and not any(term in detail for term in transient_terms):
            classified = AIProviderError(
                'provider_quota',
                'The Gemini project has exhausted its available quota. Check AI Studio quotas or wait for reset.',
            )
        else:
            classified = AIProviderError(
                'provider_rate_limit',
                'Gemini is temporarily rate-limiting requests. The analysis will be retried.',
                retryable=True,
            )
    elif code == 400:
        # A 400 is not synonymous with one specific defect. Keep a generic
        # invalid-argument category, with narrower categories only when the
        # provider's identifier/message gives a clear schema/model signal.
        if any(term in detail for term in ('response_schema', 'response schema', 'json schema', 'schema is invalid')):
            classified = AIProviderError(
                'provider_schema', 'Gemini rejected the structured response schema. Check provider schema support.',
            )
        elif any(term in detail for term in ('model does not support', 'unsupported model parameter', 'generation config')):
            classified = AIProviderError(
                'provider_model', 'Gemini rejected a setting for the configured model. Check model capabilities.',
            )
        else:
            classified = AIProviderError(
                'provider_invalid_argument',
                'Gemini rejected an analysis request argument. Check model capabilities and request configuration.',
            )
    elif isinstance(code, int) and code >= 500:
        classified = AIProviderError(
            'provider_unavailable', 'Gemini is temporarily unavailable. The analysis will be retried.', retryable=True,
        )
    else:
        classified = AIProviderError(
            'provider_request', 'Gemini rejected this analysis request. Check model access and request limits.',
        )

    safe_status = re.sub(r'[^A-Za-z0-9_.-]', '', status_name)[:64]
    logger.warning(
        'Gemini API request failed provider=%s http_status=%s provider_status=%s model=%s '
        'correlation_id=%s error_category=%s',
        'gemini', code if isinstance(code, int) else 'unknown', safe_status or 'unknown',
        model, correlation_id, classified.category,
        extra={
        'provider': 'gemini',
        'http_status': code if isinstance(code, int) else None,
        'provider_status': safe_status,
        'model': model,
        'correlation_id': correlation_id,
        'error_category': classified.category,
        },
    )
    return classified


class GeminiReviewProvider:
    provider_name = 'gemini'

    def review(self, *, instructions: str, content: str, correlation_id: str) -> ProviderResult:
        client = None
        started = time.monotonic()
        try:
            client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    timeout=settings.AI_REQUEST_TIMEOUT * 1000,
                    # Celery owns retries and backoff; avoid hidden SDK retries
                    # that could multiply requests or spend.
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            response = client.models.generate_content(
                model=settings.AI_MODEL,
                contents=content,
                config=types.GenerateContentConfig(
                    system_instruction=instructions,
                    response_mime_type='application/json',
                    response_json_schema=gemini_response_json_schema(),
                    max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS,
                    temperature=0,
                ),
            )
        except errors.APIError as exc:
            raise _classify_api_error(exc, model=settings.AI_MODEL, correlation_id=correlation_id) from exc
        except (httpx.TimeoutException, httpx.NetworkError, TimeoutError, ConnectionError) as exc:
            raise AIProviderError(
                'provider_unavailable', 'Gemini could not be reached. The analysis will be retried.', retryable=True,
            ) from exc
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    logger.debug('Gemini SDK client cleanup failed')

        try:
            response_text = response.text
            if not isinstance(response_text, str) or not response_text.strip():
                raise ValueError('No structured response text')
            output = _validated_review_output(response_text)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError, AttributeError) as exc:
            logger.warning(
                'Gemini response validation failed provider=gemini http_status=unknown provider_status=unknown '
                'model=%s correlation_id=%s error_category=invalid_output',
                settings.AI_MODEL,
                correlation_id,
                extra={
                    'provider': self.provider_name,
                    'http_status': None,
                    'provider_status': '',
                    'model': settings.AI_MODEL,
                    'correlation_id': correlation_id,
                    'error_category': 'invalid_output',
                },
            )
            raise AIProviderError(
                'invalid_output', 'Gemini returned a response that did not match the required academic review schema.',
            ) from exc

        usage = getattr(response, 'usage_metadata', None)
        input_tokens = int(getattr(usage, 'prompt_token_count', 0) or 0)
        candidates_tokens = int(getattr(usage, 'candidates_token_count', 0) or 0)
        reasoning_tokens = getattr(usage, 'thoughts_token_count', None)
        reasoning_tokens = max(0, int(reasoning_tokens)) if reasoning_tokens is not None else None
        # Gemini reports thought tokens separately; include them in total output
        # for cost/quota accounting while retaining the optional breakdown.
        output_tokens = candidates_tokens + (reasoning_tokens or 0)
        logger.info('AI review provider request completed', extra={
            'provider': self.provider_name,
            'model': settings.AI_MODEL,
            'correlation_id': correlation_id,
            'duration_ms': int((time.monotonic() - started) * 1000),
        })
        return ProviderResult(output, input_tokens, output_tokens, reasoning_tokens=reasoning_tokens)
