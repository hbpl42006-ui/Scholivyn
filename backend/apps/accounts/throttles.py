import hashlib

from django.core.cache import cache
from rest_framework.throttling import BaseThrottle, SimpleRateThrottle


class VerificationIPThrottle(SimpleRateThrottle):
    scope = 'verification_ip'

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class VerificationEmailThrottle(BaseThrottle):
    """Add a per-address limit so rotating IPs cannot spam one inbox."""

    def allow_request(self, request, view):
        address = str(request.data.get('email', request.data.get('new_email', ''))).strip().lower()
        if not address:
            return True
        digest = hashlib.sha256(address.encode()).hexdigest()
        key = f'auth:verification-email:{digest}'
        if cache.add(key, 1, timeout=60 * 60):
            return True
        try:
            return cache.incr(key) <= 3
        except ValueError:
            return False

    def wait(self):
        return 60 * 60
