from django.conf import settings

from .base import AIProviderError


def ai_configuration_error() -> str | None:
    if not settings.AI_ANALYSIS_ENABLED:
        return 'AI analysis is disabled by server configuration.'
    if settings.AI_PROVIDER not in {'openai', 'gemini', 'groq'}:
        return 'The configured AI provider is not supported.'
    if settings.AI_PROVIDER == 'openai' and not settings.OPENAI_API_KEY:
        return 'AI analysis is not configured with an OpenAI API key.'
    if settings.AI_PROVIDER == 'gemini' and not settings.GEMINI_API_KEY:
        return 'AI analysis is not configured with a Gemini API key.'
    if settings.AI_PROVIDER == 'groq' and not settings.GROQ_API_KEY:
        return 'AI analysis is not configured with a Groq API key.'
    if not settings.AI_MODEL:
        return 'AI analysis is not configured with a model identifier.'
    return None


def get_provider():
    error = ai_configuration_error()
    if error:
        raise AIProviderError('not_configured', error)
    if settings.AI_PROVIDER == 'openai':
        from .openai_provider import OpenAIReviewProvider
        return OpenAIReviewProvider()
    if settings.AI_PROVIDER == 'gemini':
        from .gemini_provider import GeminiReviewProvider
        return GeminiReviewProvider()
    if settings.AI_PROVIDER == 'groq':
        from .groq_provider import GroqReviewProvider
        return GroqReviewProvider()
    raise AIProviderError('provider_unavailable', 'The configured AI provider is unavailable.')
