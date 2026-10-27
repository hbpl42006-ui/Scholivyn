"""Groq structured academic reviews through its OpenAI-compatible API."""

import json
import logging
import math
import time

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError

from django.conf import settings

from apps.intelligence.schemas import SectionReviewOutput
from apps.intelligence.services.analyzer import estimate_tokens
from .base import AIProviderError, ProviderResult
from .groq_quota import (observe_response_headers, rate_limit_wait_from_headers,
                         reserve_request, reconcile_usage)

logger = logging.getLogger(__name__)

GROQ_BASE_URL = 'https://api.groq.com/openai/v1'


def groq_response_json_schema() -> dict:
    """Create Groq strict-mode schema; Pydantic remains the authoritative validator.

    Groq strict mode requires every field to be required and every object closed.
    It also accepts nullable unions as a string/null type array. Pydantic's length
    and collection constraints are enforced after the response, not sent as
    provider-specific schema keywords.
    """
    generated = SectionReviewOutput.model_json_schema()
    definitions = generated.get('$defs', {})

    def convert(node):
        if not isinstance(node, dict):
            raise ValueError('Unexpected node in generated Groq schema')

        reference = node.get('$ref')
        if reference:
            prefix = '#/$defs/'
            name = reference[len(prefix):] if reference.startswith(prefix) else None
            if not name or name not in definitions:
                raise ValueError('Unsupported reference in generated Groq schema')
            expanded = convert(definitions[name])
            siblings = {key: value for key, value in node.items() if key != '$ref'}
            if siblings:
                expanded.update(convert(siblings))
            return expanded

        if 'anyOf' in node:
            branches = node['anyOf']
            if len(branches) == 2:
                converted = [convert(branch) for branch in branches]
                types = [branch.get('type') for branch in converted]
                if set(types) == {'string', 'null'}:
                    return {'type': ['string', 'null']}
            raise ValueError('Unsupported union in generated Groq schema')

        node_type = node.get('type')
        if node_type == 'object':
            properties = node.get('properties', {})
            return {
                'type': 'object',
                'properties': {name: convert(value) for name, value in properties.items()},
                'required': list(properties),
                'additionalProperties': False,
            }
        if node_type == 'array':
            return {'type': 'array', 'items': convert(node['items'])}
        if node_type == 'string' and 'enum' in node:
            return {'type': 'string', 'enum': list(node['enum'])}
        if node_type in {'string', 'integer', 'number', 'boolean', 'null'}:
            return {'type': node_type}
        raise ValueError('Unsupported field in generated Groq schema')

    schema = convert({key: value for key, value in generated.items() if key != '$defs'})
    if schema.get('type') != 'object' or not schema.get('properties'):
        raise ValueError('Generated Groq schema has an unexpected root')
    return schema


def _safe_provider_error(status_code: int | None, headers=None) -> AIProviderError:
    if status_code == 401 or status_code == 403:
        return AIProviderError('provider_authentication', 'Groq authentication or access was denied. Check server-side configuration.')
    if status_code == 402:
        return AIProviderError('provider_billing', 'The Groq account has a billing restriction. Check its billing configuration.')
    if status_code == 404:
        return AIProviderError('provider_model', 'The configured Groq model is unavailable. Check the model identifier.')
    if status_code == 429:
        return AIProviderError('provider_rate_limit', 'Groq is temporarily rate-limiting requests.', retryable=True,
                               retry_after_seconds=rate_limit_wait_from_headers(headers))
    if status_code == 413:
        return AIProviderError('provider_payload_too_large', 'Groq rejected an oversized analysis request; the section will be split.')
    if status_code is not None and status_code >= 500:
        return AIProviderError('provider_unavailable', 'Groq is temporarily unavailable. The analysis will be retried.', retryable=True)
    if status_code == 400:
        return AIProviderError('provider_invalid_argument', 'Groq rejected the analysis request configuration.')
    return AIProviderError('provider_request', 'Groq rejected the analysis request.')


def _raise_logged_provider_error(exc, *, model: str, correlation_id: str):
    status_code = getattr(exc, 'status_code', None)
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', None)
    category = _safe_provider_error(status_code, headers)
    safe_status = status_code if isinstance(status_code, int) else 'unknown'
    logger.warning(
        'Groq API request failed provider=groq http_status=%s model=%s correlation_id=%s error_category=%s',
        safe_status, model, correlation_id, category.category,
        extra={
            'provider': 'groq', 'http_status': status_code if isinstance(status_code, int) else None,
            'model': model, 'correlation_id': correlation_id, 'error_category': category.category,
        },
    )
    raise category from exc


class GroqReviewProvider:
    provider_name = 'groq'

    def review(self, *, instructions: str, content: str, correlation_id: str) -> ProviderResult:
        client = None
        quota_client = None
        quota_keys = None
        reservation_id = None
        started = time.monotonic()
        try:
            estimated_input = estimate_tokens(instructions) + estimate_tokens(content)
            # The local tokenizer may not match the provider tokenizer exactly; add headroom.
            input_budget = math.ceil(estimated_input * 1.15) + 256
            quota_client, quota_keys, token_budget, reservation_id = reserve_request(
                settings.AI_MODEL, input_budget + settings.AI_MAX_OUTPUT_TOKENS,
            )
            client = OpenAI(
                api_key=settings.GROQ_API_KEY,
                base_url=GROQ_BASE_URL,
                timeout=settings.AI_REQUEST_TIMEOUT,
                max_retries=0,
            )
            raw_response = client.chat.completions.with_raw_response.create(
                model=settings.AI_MODEL,
                messages=[
                    {'role': 'system', 'content': instructions},
                    {'role': 'user', 'content': content},
                ],
                response_format={
                    'type': 'json_schema',
                    'json_schema': {
                        'name': 'section_review_output',
                        'strict': True,
                        'schema': groq_response_json_schema(),
                    },
                },
                max_completion_tokens=settings.AI_MAX_OUTPUT_TOKENS,
            )
            response = raw_response.parse()
            response_headers = dict(raw_response.headers)
            observe_response_headers(quota_client, settings.AI_MODEL, response_headers)
        except (AuthenticationError, RateLimitError, BadRequestError, APIStatusError) as exc:
            error_response = getattr(exc, 'response', None)
            error_headers = getattr(error_response, 'headers', None)
            if quota_client is not None:
                observe_response_headers(quota_client, settings.AI_MODEL, error_headers)
                # A definitive 4xx response did not generate a completion. Keep
                # the request-rate reservation, but release its unused token cap.
                if (status_code := getattr(exc, 'status_code', None)) in {400, 401, 402, 403, 404, 413, 429}:
                    try:
                        reconcile_usage(quota_client, quota_keys, token_budget, 0, 0, reservation_id)
                    except Exception:
                        logger.info('Groq token reservation reconciliation deferred', extra={
                            'provider': 'groq', 'model': settings.AI_MODEL,
                            'correlation_id': correlation_id, 'error_category': 'quota_reconciliation_deferred',
                        })
                quota_client.close()
                quota_client = None
            _raise_logged_provider_error(exc, model=settings.AI_MODEL, correlation_id=correlation_id)
        except (APITimeoutError, APIConnectionError, httpx.TimeoutException, httpx.NetworkError, TimeoutError, ConnectionError) as exc:
            error = AIProviderError(
                'provider_unavailable', 'Groq could not be reached. The analysis will be retried.', retryable=True,
            )
            logger.warning(
                'Groq API request failed provider=groq http_status=unknown model=%s correlation_id=%s error_category=%s',
                settings.AI_MODEL, correlation_id, error.category,
                extra={'provider': 'groq', 'http_status': None, 'model': settings.AI_MODEL,
                       'correlation_id': correlation_id, 'error_category': error.category},
            )
            if quota_client is not None:
                quota_client.close()
                quota_client = None
            raise error from exc
        except Exception:
            if quota_client is not None:
                quota_client.close()
                quota_client = None
            raise
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    logger.debug('Groq SDK client cleanup failed')

        usage = getattr(response, 'usage', None)
        input_tokens = int(getattr(usage, 'prompt_tokens', 0) or 0)
        output_tokens = int(getattr(usage, 'completion_tokens', 0) or 0)
        token_details = getattr(usage, 'completion_tokens_details', None)
        reasoning_tokens = getattr(token_details, 'reasoning_tokens', None)
        if reasoning_tokens is None:
            reasoning_tokens = getattr(usage, 'reasoning_tokens', None)
        if reasoning_tokens is not None:
            reasoning_tokens = max(0, int(reasoning_tokens))
        if quota_client is not None and quota_keys is not None and usage is not None:
            reconcile_usage(quota_client, quota_keys, token_budget, input_tokens, output_tokens, reservation_id)

        try:
            text = response.choices[0].message.content
            if not isinstance(text, str) or not text.strip():
                raise ValueError('No structured response text')
            output = SectionReviewOutput.model_validate_json(text)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError, AttributeError, IndexError) as exc:
            logger.warning(
                'Groq response validation failed provider=groq http_status=unknown model=%s correlation_id=%s error_category=invalid_output',
                settings.AI_MODEL, correlation_id,
                extra={'provider': 'groq', 'http_status': None, 'model': settings.AI_MODEL,
                       'correlation_id': correlation_id, 'error_category': 'invalid_output'},
            )
            raise AIProviderError(
                'invalid_output', 'Groq returned a response that did not match the required academic review schema.',
            ) from exc

        if quota_client is not None:
            quota_client.close()
        logger.info('AI review provider request completed', extra={
            'provider': self.provider_name, 'model': settings.AI_MODEL,
            'correlation_id': correlation_id,
            'duration_ms': int((time.monotonic() - started) * 1000),
        })
        return ProviderResult(output, input_tokens, output_tokens, reasoning_tokens=reasoning_tokens)
