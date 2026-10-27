import json
import hashlib
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.core.cache import cache


class JournalProviderError(Exception):
    def __init__(self, category, retryable=False, retry_after=None):
        super().__init__(category)
        self.category, self.retryable, self.retry_after = category, retryable, retry_after


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(url, host, provider, *, params=''):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != host or parts.username or parts.password:
        raise JournalProviderError('provider_url_rejected')
    key = 'publishing-provider-rate:' + provider
    cache_key = 'publishing-response:' + hashlib.sha256((url + '?' + params).encode()).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    if not cache.add(key, '1', timeout=1):
        raise JournalProviderError('provider_rate_limited', True, 1)
    request = Request(url + ('?' + params if params else ''), headers={
        'Accept':'application/json', 'User-Agent':'Scholivyn journal metadata integration (scholarly catalog lookup)'})
    try:
        with build_opener(_NoRedirect).open(request, timeout=settings.JOURNAL_PROVIDER_TIMEOUT) as response:
            payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise JournalProviderError('provider_response_too_large')
            value = json.loads(payload.decode('utf-8'))
            cache.set(cache_key, value, timeout=1800)
            return value
    except HTTPError as exc:
        retry = None
        try: retry = min(1800, max(1, int(exc.headers.get('Retry-After', '1'))))
        except (TypeError, ValueError): pass
        if exc.code == 429: raise JournalProviderError('provider_rate_limited', True, retry) from None
        if 500 <= exc.code <= 599: raise JournalProviderError('provider_unavailable', True, retry) from None
        if exc.code == 404: return None
        raise JournalProviderError('provider_request_rejected') from None
    except (URLError, TimeoutError, OSError):
        raise JournalProviderError('provider_unavailable', True) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise JournalProviderError('provider_malformed_response') from None
