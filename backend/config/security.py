"""Environment-driven production security defaults.

Development remains compatible with plain HTTP. Production defaults are secure
when DEBUG is disabled, while explicit environment values allow controlled
deployment behind a correctly configured TLS-terminating proxy.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from django.core.exceptions import ImproperlyConfigured


def env_bool(name: str, default: bool, environ: Mapping[str, str] = os.environ) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def security_settings(debug: bool, environ: Mapping[str, str] = os.environ) -> dict:
    secure_default = not debug
    return {
        "SECURE_SSL_REDIRECT": env_bool("SECURE_SSL_REDIRECT", secure_default, environ),
        "SESSION_COOKIE_SECURE": env_bool("SESSION_COOKIE_SECURE", secure_default, environ),
        "CSRF_COOKIE_SECURE": env_bool("CSRF_COOKIE_SECURE", secure_default, environ),
        "SECURE_HSTS_SECONDS": int(environ.get("SECURE_HSTS_SECONDS", "0" if debug else "31536000")),
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False, environ),
        "SECURE_HSTS_PRELOAD": env_bool("SECURE_HSTS_PRELOAD", False, environ),
    }


def validate_production_secrets(debug: bool, secret_key: str, jwt_signing_key: str) -> None:
    """Fail closed in production without rotating or generating signing keys."""
    if debug:
        return
    for name, value, minimum in (
        ("SECRET_KEY", secret_key, 50),
        ("JWT_SIGNING_KEY", jwt_signing_key, 32),
    ):
        if len(value) < minimum or len(set(value)) < 5 or value.startswith("django-insecure-"):
            raise ImproperlyConfigured(
                f"{name} must be configured with a high-entropy secret of at least {minimum} characters. "
                "Load the existing value from your deployment secret manager; do not generate or rotate it automatically."
            )


def csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]
