"""Distributed, conservative Groq request budgeting backed by the task Redis."""

import hashlib
import math
import time
from uuid import uuid4

import redis
from django.conf import settings

from .base import AIProviderError


_RESERVE_SCRIPT = r"""
local now = tonumber(ARGV[1])
local tokens = tonumber(ARGV[2])
local member = ARGV[3]
local limits = {tonumber(ARGV[4]), tonumber(ARGV[5]), tonumber(ARGV[6]), tonumber(ARGV[7])}
local windows = {60, 86400, 60, 86400}
local function clean(zset, amounts, cutoff)
  local expired = redis.call('ZRANGEBYSCORE', zset, '-inf', cutoff)
  if amounts then for _, id in ipairs(expired) do redis.call('HDEL', amounts, id) end end
  redis.call('ZREMRANGEBYSCORE', zset, '-inf', cutoff)
end
clean(KEYS[1], nil, now - windows[1])
clean(KEYS[2], nil, now - windows[2])
clean(KEYS[3], KEYS[7], now - windows[3])
clean(KEYS[4], KEYS[8], now - windows[4])
local function request_wait(zset, limit, window)
  if redis.call('ZCARD', zset) + 1 <= limit then return 0 end
  local oldest = redis.call('ZRANGE', zset, 0, 0, 'WITHSCORES')
  if #oldest < 2 then return 1 end
  return math.max(1, math.ceil(tonumber(oldest[2]) + window - now))
end
local function token_wait(zset, amounts, limit, window)
  local members = redis.call('ZRANGE', zset, 0, -1, 'WITHSCORES')
  local total = 0
  for i = 1, #members, 2 do total = total + tonumber(redis.call('HGET', amounts, members[i]) or '0') end
  if total + tokens <= limit then return 0 end
  local must_expire = total + tokens - limit
  local expired_tokens = 0
  for i = 1, #members, 2 do
    expired_tokens = expired_tokens + tonumber(redis.call('HGET', amounts, members[i]) or '0')
    if expired_tokens >= must_expire then
      return math.max(1, math.ceil(tonumber(members[i + 1]) + window - now))
    end
  end
  return 1
end
local waits = {
  request_wait(KEYS[1], limits[1], windows[1]),
  request_wait(KEYS[2], limits[2], windows[2]),
  token_wait(KEYS[3], KEYS[7], limits[3], windows[3]),
  token_wait(KEYS[4], KEYS[8], limits[4], windows[4]),
}
for _, wait in ipairs(waits) do if wait > 0 then return {0, wait} end end
local observed_tokens = redis.call('GET', KEYS[5])
if observed_tokens and tonumber(observed_tokens) < tokens then
  return {0, math.max(1, redis.call('TTL', KEYS[5]))}
end
local observed_requests = redis.call('GET', KEYS[6])
if observed_requests and tonumber(observed_requests) < 1 then
  return {0, math.max(1, redis.call('TTL', KEYS[6]))}
end
for i = 1, 4 do
  redis.call('ZADD', KEYS[i], now, member)
  redis.call('EXPIRE', KEYS[i], 172800)
end
redis.call('HSET', KEYS[7], member, tokens)
redis.call('HSET', KEYS[8], member, tokens)
redis.call('EXPIRE', KEYS[7], 172800)
redis.call('EXPIRE', KEYS[8], 172800)
if observed_tokens then redis.call('DECRBY', KEYS[5], tokens) end
if observed_requests then redis.call('DECRBY', KEYS[6], 1) end
return {1, 0}
"""

_RECONCILE_SCRIPT = r"""
local member = ARGV[1]
local actual = tonumber(ARGV[2])
for i = 1, 2 do
  local score = redis.call('ZSCORE', KEYS[i], member)
  if score then
    if actual > 0 then
      redis.call('HSET', KEYS[i + 2], member, actual)
    else
      redis.call('ZREM', KEYS[i], member)
      redis.call('HDEL', KEYS[i + 2], member)
    end
  end
end
return 1
"""


def _quota_keys(model: str):
    model_key = hashlib.sha256(model.encode('utf-8')).hexdigest()[:16]
    prefix = f'scholivyn:groq-quota:v1:{model_key}'
    return (
        [f'{prefix}:rpm-window', f'{prefix}:rpd-window', f'{prefix}:tpm-window', f'{prefix}:tpd-window',
         f'{prefix}:observed-tpm', f'{prefix}:observed-rpd', f'{prefix}:tpm-amounts', f'{prefix}:tpd-amounts'],
        60, 86400,
    )


def _client():
    broker = settings.CELERY_BROKER_URL
    if not broker.startswith(('redis://', 'rediss://', 'unix://')):
        raise ConnectionError('A Redis Celery broker is required for shared provider quotas.')
    return redis.Redis.from_url(broker, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)


def reserve_request(model: str, token_budget: int) -> tuple[object, list[str], int]:
    """Atomically reserve one request and its conservative input+output token cap."""
    limit_tpm = int(settings.GROQ_TPM_LIMIT)
    if token_budget > limit_tpm:
        raise AIProviderError(
            'provider_payload_too_large',
            'This manuscript section exceeds the configured Groq per-minute token budget and must be split.',
        )
    keys, minute_wait, day_wait = _quota_keys(model)
    member = uuid4().hex
    args = [time.time(), token_budget, member, settings.GROQ_RPM_LIMIT, settings.GROQ_RPD_LIMIT,
            settings.GROQ_TPM_LIMIT, settings.GROQ_TPD_LIMIT, minute_wait, day_wait]
    client = None
    try:
        client = _client()
        allowed, wait = client.eval(_RESERVE_SCRIPT, len(keys), *keys, *args)
    except Exception as exc:
        if client is not None:
            client.close()
        raise AIProviderError(
            'provider_quota_unavailable', 'Shared AI quota coordination is temporarily unavailable.',
            retryable=True, retry_after_seconds=30,
        ) from exc
    if not allowed:
        client.close()
        raise AIProviderError(
            'provider_rate_limit', 'The configured Groq request or token budget is temporarily exhausted.',
            retryable=True, retry_after_seconds=max(1, int(wait)),
        )
    return client, keys, token_budget, member


def reconcile_usage(client, keys: list[str], reserved_tokens: int, input_tokens: int, output_tokens: int,
                    reservation_id: str):
    actual_tokens = max(0, int(input_tokens)) + max(0, int(output_tokens))
    if int(reserved_tokens) != actual_tokens:
        client.eval(_RECONCILE_SCRIPT, 4, keys[2], keys[3], keys[6], keys[7], reservation_id, actual_tokens)


def observe_response_headers(client, model: str, headers):
    """Honor provider-reported remaining quotas without logging raw headers."""
    if not headers:
        return
    normalized = {str(key).lower(): str(value).strip() for key, value in headers.items()}
    keys, minute_wait, day_wait = _quota_keys(model)
    try:
        remaining_tokens = normalized.get('x-ratelimit-remaining-tokens')
        reset_tokens = normalized.get('x-ratelimit-reset-tokens')
        if remaining_tokens is not None:
            client.set(keys[4], max(0, int(remaining_tokens)), ex=_duration_seconds(reset_tokens, minute_wait))
        remaining_requests = normalized.get('x-ratelimit-remaining-requests')
        reset_requests = normalized.get('x-ratelimit-reset-requests')
        if remaining_requests is not None:
            client.set(keys[5], max(0, int(remaining_requests)), ex=_duration_seconds(reset_requests, day_wait))
    except (TypeError, ValueError, redis.RedisError):
        # Malformed/unsupported quota headers are ignored; local configured limits remain active.
        return


def _duration_seconds(value: str | None, fallback: int) -> int:
    if not value:
        return fallback
    # Groq reset strings may be values such as "2m59.5s" or "5.2s".
    import re
    total = 0.0
    for number, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(h|m|s)', value.lower()):
        total += float(number) * {'h': 3600, 'm': 60, 's': 1}[unit]
    if total <= 0:
        try:
            total = float(value)
        except ValueError:
            return fallback
    return max(1, math.ceil(total))


def retry_after_from_headers(headers) -> float | None:
    if not headers:
        return None
    value = next((str(v) for k, v in headers.items() if str(k).lower() == 'retry-after'), None)
    if not value:
        return None
    try:
        return max(1.0, float(value.strip()))
    except ValueError:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        try:
            return max(1.0, (parsedate_to_datetime(value).astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def rate_limit_wait_from_headers(headers) -> float | None:
    if not headers:
        return None
    normalized = {str(k).lower(): str(v).strip() for k, v in headers.items()}
    delays = [retry_after_from_headers(headers)]
    if normalized.get('x-ratelimit-remaining-tokens') == '0':
        delays.append(_duration_seconds(normalized.get('x-ratelimit-reset-tokens'), 60))
    if normalized.get('x-ratelimit-remaining-requests') == '0':
        delays.append(_duration_seconds(normalized.get('x-ratelimit-reset-requests'), 86400))
    available = [delay for delay in delays if delay is not None]
    return max(available) if available else None
