import logging
import time

from django.conf import settings
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, BadRequestError, OpenAI, RateLimitError
from pydantic import ValidationError

from apps.intelligence.schemas import SectionReviewOutput
from .base import AIProviderError, ProviderResult

logger = logging.getLogger(__name__)


def is_billing_limit_error(exc) -> bool:
    """Recognize quota/billing 429s without exposing provider error bodies."""
    body = getattr(exc, 'body', None)
    if not isinstance(body, dict):
        return False
    details = body.get('error', body)
    if not isinstance(details, dict):
        return False
    code = str(details.get('code') or '').casefold()
    error_type = str(details.get('type') or '').casefold()
    return code in {'insufficient_quota', 'billing_hard_limit_reached', 'billing_not_active'} or error_type in {
        'insufficient_quota', 'billing_hard_limit_reached', 'billing_not_active',
    }


class OpenAIReviewProvider:
    provider_name = 'openai'

    def review(self, *, instructions: str, content: str, correlation_id: str) -> ProviderResult:
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.AI_REQUEST_TIMEOUT, max_retries=0)
        started = time.monotonic()
        try:
            response = client.responses.parse(model=settings.AI_MODEL, instructions=instructions,
                                              input=content, text_format=SectionReviewOutput,
                                              max_output_tokens=settings.AI_MAX_OUTPUT_TOKENS)
            parsed = response.output_parsed
            if parsed is None:
                raise AIProviderError('invalid_output', 'The AI provider returned no structured review.')
            usage = response.usage
            logger.info('AI review provider request completed', extra={
                'provider': self.provider_name, 'model': settings.AI_MODEL,
                'correlation_id': correlation_id,
                'duration_ms': int((time.monotonic() - started) * 1000),
            })
            output_details = getattr(usage, 'output_tokens_details', None) if usage else None
            reasoning_tokens = getattr(output_details, 'reasoning_tokens', None)
            if reasoning_tokens is not None:
                reasoning_tokens = max(0, int(reasoning_tokens))
            return ProviderResult(
                parsed, usage.input_tokens if usage else 0, usage.output_tokens if usage else 0,
                reasoning_tokens=reasoning_tokens,
            )
        except AIProviderError:
            raise
        except AuthenticationError as exc:
            raise AIProviderError('provider_authentication', 'AI provider authentication failed. Check server configuration.') from exc
        except RateLimitError as exc:
            if is_billing_limit_error(exc):
                raise AIProviderError(
                    'provider_billing',
                    'The configured AI account has no available credits or its billing limit was reached. Contact the administrator.',
                ) from exc
            raise AIProviderError('provider_rate_limit', 'The AI provider is temporarily rate-limiting requests.', retryable=True) from exc
        except (APITimeoutError, APIConnectionError) as exc:
            raise AIProviderError('provider_unavailable', 'The AI provider could not be reached before the request timed out.', retryable=True) from exc
        except BadRequestError as exc:
            raise AIProviderError('provider_request', 'The AI provider rejected this review request.') from exc
        except APIStatusError as exc:
            retryable = exc.status_code >= 500
            raise AIProviderError('provider_server' if retryable else 'provider_request',
                                  'The AI provider is temporarily unavailable.' if retryable else 'The AI provider rejected this review request.',
                                  retryable=retryable) from exc
        except ValidationError as exc:
            raise AIProviderError('invalid_output', 'The AI provider response did not match the required review schema.') from exc
