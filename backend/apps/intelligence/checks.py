from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security)
def security_configuration_check(app_configs, **kwargs):
    issues = []
    signing_key = settings.SIMPLE_JWT.get('SIGNING_KEY', '')
    if not settings.DEBUG and (len(signing_key) < 32 or signing_key in ('dev-only-secret', 'change-me-in-development')):
        issues.append(Error(
            'Set a high-entropy JWT_SIGNING_KEY (at least 32 characters) before production.',
            hint='Key rotation invalidates existing access and refresh tokens; plan a user re-authentication window.',
            id='intelligence.E001',
        ))
    provider_keys = {
        'openai': settings.OPENAI_API_KEY,
        'gemini': settings.GEMINI_API_KEY,
        'groq': settings.GROQ_API_KEY,
    }
    provider_key = provider_keys.get(settings.AI_PROVIDER)
    if settings.AI_ANALYSIS_ENABLED and (not provider_key or not settings.AI_MODEL):
        issues.append(Warning(
            'AI analysis is enabled but the provider key or model identifier is missing; analysis requests will be rejected.',
            id='intelligence.W001',
        ))
    return issues
