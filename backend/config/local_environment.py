"""Load a small, explicit local-only allowlist from the repository .env.

Docker Compose already injects its environment into Linux containers. Importing
the repository .env wholesale on Windows would select Docker-only PostgreSQL
and Redis hosts, so the local loader deliberately accepts an AI-only allowlist.
Explicit process environment variables always take precedence.
"""

import os
from pathlib import Path
from typing import MutableMapping

from dotenv import dotenv_values


LOCAL_AI_ENV_KEYS = frozenset({
    'AI_PROVIDER', 'AI_MODEL', 'AI_ANALYSIS_ENABLED', 'AI_REQUEST_TIMEOUT',
    'AI_MAX_DOCUMENT_WORDS', 'AI_MAX_CHUNK_TOKENS', 'AI_MAX_OUTPUT_TOKENS', 'AI_MAX_RETRIES',
    'AI_RETRY_BASE_DELAY', 'AI_RETRY_MAX_DELAY',
    'GROQ_RPM_LIMIT', 'GROQ_RPD_LIMIT', 'GROQ_TPM_LIMIT', 'GROQ_TPD_LIMIT', 'AI_WORKER_LEASE_SECONDS',
    'AI_MAX_RETRIES', 'AI_MAX_ACTIVE_JOBS_PER_USER', 'AI_ANALYSIS_RATE',
    'AI_ANALYSIS_READ_RATE', 'AI_INPUT_COST_PER_MILLION', 'AI_OUTPUT_COST_PER_MILLION',
    'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GROQ_API_KEY', 'GROQ_MODEL', 'OPENALEX_API_KEY',
    # Billing controls and test credentials only; never import Docker service
    # addresses, database credentials, or production payment credentials by name.
    'PAYMENT_MODE', 'BILLING_ENFORCEMENT_ENABLED', 'SUBSCRIPTION_RENEWALS_ENABLED',
    'RAZORPAY_KEY_ID', 'RAZORPAY_KEY_SECRET', 'RAZORPAY_WEBHOOK_SECRET',
    'BILLING_ORDER_RATE', 'BILLING_VERIFY_RATE', 'BILLING_WEBHOOK_RATE',
    'BILLING_ADMIN_RATE',
})


def load_local_ai_environment(
    environ: MutableMapping[str, str] | None = None,
    env_path: Path | None = None,
    *,
    is_windows: bool | None = None,
) -> None:
    """Import allowlisted AI/billing variables from root .env on Windows only."""
    target = os.environ if environ is None else environ
    if is_windows is None:
        is_windows = os.name == 'nt'
    if not is_windows:
        return

    path = env_path or Path(__file__).resolve().parents[2] / '.env'
    if not path.is_file():
        return

    for key, value in dotenv_values(path, interpolate=False).items():
        if key in LOCAL_AI_ENV_KEYS and value is not None and key not in target:
            target[key] = value
