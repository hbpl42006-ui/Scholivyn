"""Safe HTTP primitives for fixed-host scholarly metadata providers."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.core.cache import cache


class MetadataProviderError(Exception):
    def __init__(self, category, *, retryable=False, retry_after=None):
        super().__init__(category)
        self.category, self.retryable, self.retry_after = category, retryable, retry_after


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_json_get(url, allowed_host, provider, params=None):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != allowed_host or parts.username or parts.password:
        raise MetadataProviderError('invalid_provider_url')
    lock_key = f'citation-meta-rate:{provider}'
    if not cache.add(lock_key, '1', timeout=1):
        raise MetadataProviderError('rate_limited', retryable=True, retry_after=1)
    request = Request(url + ('?' + params if params else ''), headers={
        'Accept': 'application/json',
        'User-Agent': 'Scholivyn/1.0 (citation metadata lookup; administrator contact configured separately)'})
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=settings.CITATION_PROVIDER_TIMEOUT) as response:
            content = response.read(settings.CITATION_PROVIDER_MAX_RESPONSE_BYTES + 1)
            if len(content) > settings.CITATION_PROVIDER_MAX_RESPONSE_BYTES:
                raise MetadataProviderError('response_too_large')
            return json.loads(content.decode('utf-8'))
    except HTTPError as exc:
        retry_after = None
        try: retry_after = min(3600, max(1, int(exc.headers.get('Retry-After', '1'))))
        except (TypeError, ValueError): pass
        if exc.code == 429: raise MetadataProviderError('rate_limited', retryable=True, retry_after=retry_after) from None
        if 500 <= exc.code <= 599: raise MetadataProviderError('provider_unavailable', retryable=True) from None
        if exc.code == 404: raise MetadataProviderError('not_found') from None
        if 300 <= exc.code <= 399: raise MetadataProviderError('provider_redirect_rejected') from None
        raise MetadataProviderError('provider_request_rejected') from None
    except (URLError, TimeoutError, OSError):
        raise MetadataProviderError('network_unavailable', retryable=True) from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MetadataProviderError('malformed_provider_response') from None
