import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from config.security import csv_env, security_settings, validate_production_secrets
BASE_DIR = Path(__file__).resolve().parent.parent
if os.name == 'nt':
    from config.local_environment import load_local_ai_environment
    load_local_ai_environment()

SECRET_KEY = os.getenv('SECRET_KEY', 'dev-only-secret')
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,backend').split(',')
JWT_SIGNING_KEY = os.getenv('JWT_SIGNING_KEY', SECRET_KEY)
validate_production_secrets(DEBUG, SECRET_KEY, JWT_SIGNING_KEY)
if not DEBUG and ('*' in ALLOWED_HOSTS or not any(host.strip() for host in ALLOWED_HOSTS)):
    raise ImproperlyConfigured('Set explicit production ALLOWED_HOSTS; wildcard hosts are not permitted.')
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','corsheaders','rest_framework','drf_spectacular','apps.accounts','apps.research','apps.intelligence','apps.similarity','apps.citations','apps.publishing','apps.billing.apps.BillingConfig']
MIDDLEWARE = ['corsheaders.middleware.CorsMiddleware','django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
if os.getenv('POSTGRES_HOST'):
    DATABASES = {'default': {'ENGINE':'django.db.backends.postgresql','NAME':os.getenv('POSTGRES_DB','scholivyn'),'USER':os.getenv('POSTGRES_USER','scholivyn'),'PASSWORD':os.getenv('POSTGRES_PASSWORD','scholivyn'),'HOST':os.getenv('POSTGRES_HOST'),'PORT':os.getenv('POSTGRES_PORT','5432')}}
else:
    DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':BASE_DIR / 'db.sqlite3'}}
AUTH_USER_MODEL = 'accounts.User'
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('rest_framework_simplejwt.authentication.JWTAuthentication',),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_RATES': {
        'verification_ip': '5/hour',
        'verification_email': '10/hour',
        'ai_analysis_read': os.getenv('AI_ANALYSIS_READ_RATE', '120/hour'),
        'ai_analysis': os.getenv('AI_ANALYSIS_RATE', '3/hour'),
      'billing_order': os.getenv('BILLING_ORDER_RATE', '10/hour'),
      'billing_verify': os.getenv('BILLING_VERIFY_RATE', '30/hour'),
      'billing_webhook': os.getenv('BILLING_WEBHOOK_RATE', '600/hour'),
      'billing_admin': os.getenv('BILLING_ADMIN_RATE', '120/hour'),
    },
}
from datetime import timedelta
SIMPLE_JWT = {'ACCESS_TOKEN_LIFETIME': timedelta(minutes=5), 'REFRESH_TOKEN_LIFETIME': timedelta(days=7), 'ROTATE_REFRESH_TOKENS': True, 'BLACKLIST_AFTER_ROTATION': True, 'UPDATE_LAST_LOGIN': True,
              'SIGNING_KEY': JWT_SIGNING_KEY}
PASSWORD_RESET_TIMEOUT = int(os.getenv('EMAIL_ACTION_TOKEN_TIMEOUT', '86400'))
SPECTACULAR_SETTINGS = {
    'TITLE': 'Scholivyn API', 'VERSION': '1.0.0', 'DESCRIPTION': 'Research workspace API',
    'ENUM_NAME_OVERRIDES': {
        'ResearchProjectStatusEnum': 'apps.research.models.ResearchProject.Status',
        'DocumentProcessingStatusEnum': 'apps.research.models.DocumentVersion.ProcessingStatus',
        'AnalysisJobStatusEnum': 'apps.intelligence.models.AnalysisJob.Status',
        'AnalysisSectionStatusEnum': 'apps.intelligence.models.AnalysisSectionResult.ProcessingStatus',
        'AnalysisChunkStatusEnum': 'apps.intelligence.models.AnalysisChunkResult.Status',
        'AnalysisIssueSeverityEnum': 'apps.intelligence.models.AnalysisIssue.Severity',
        'AnalysisIssueResolutionEnum': 'apps.intelligence.models.AnalysisIssue.Resolution',
        'WritingSuggestionStatusEnum': 'apps.intelligence.models.WritingSuggestion.Status',
    },
}
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:3001').rstrip('/')
CORS_ALLOWED_ORIGINS = [FRONTEND_URL]
CSRF_TRUSTED_ORIGINS = csv_env('CSRF_TRUSTED_ORIGINS')
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = os.getenv('SECURE_REFERRER_POLICY', 'strict-origin-when-cross-origin')
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
globals().update(security_settings(DEBUG))
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'accounts@scholivyn.local')
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'true').lower() == 'true'
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'false').lower() == 'true'
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '15'))
REDIS_URL = os.getenv('REDIS_URL', '')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', REDIS_URL or 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = os.getenv('CELERY_TASK_ALWAYS_EAGER', 'false').lower() == 'true'
CELERY_TASK_EAGER_PROPAGATES = True
PAYMENT_MODE = os.getenv('PAYMENT_MODE', 'mock').strip().lower()
BILLING_ENFORCEMENT_ENABLED = os.getenv('BILLING_ENFORCEMENT_ENABLED', 'false').lower() == 'true'
SUBSCRIPTION_RENEWALS_ENABLED = os.getenv('SUBSCRIPTION_RENEWALS_ENABLED', 'false').lower() == 'true'
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')
CELERY_TASK_ROUTES = {'intelligence.process_analysis_job': {'queue': 'ai'}, 'similarity.process_similarity_job': {'queue': 'celery'}, 'citations.process_citation_analysis': {'queue': 'celery'}, 'citations.verify_citation_metadata': {'queue': 'celery'}, 'publishing.process_journal_recommendation': {'queue': 'celery'}}
AI_PROVIDER = os.getenv('AI_PROVIDER', 'openai').strip().lower()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
GROQ_MODEL = os.getenv('GROQ_MODEL', '').strip()
AI_MODEL = (GROQ_MODEL if AI_PROVIDER == 'groq' else os.getenv('AI_MODEL', '').strip())
AI_ANALYSIS_ENABLED = os.getenv('AI_ANALYSIS_ENABLED', 'false').lower() == 'true'
AI_REQUEST_TIMEOUT = max(5, int(os.getenv('AI_REQUEST_TIMEOUT', '120')))
AI_MAX_DOCUMENT_WORDS = max(1000, int(os.getenv('AI_MAX_DOCUMENT_WORDS', '25000')))
AI_MAX_CHUNK_TOKENS = max(256, int(os.getenv('AI_MAX_CHUNK_TOKENS', '6000')))
AI_MAX_OUTPUT_TOKENS = max(256, int(os.getenv('AI_MAX_OUTPUT_TOKENS', '4000')))
AI_MAX_RETRIES = min(5, max(0, int(os.getenv('AI_MAX_RETRIES', '3'))))
AI_RETRY_BASE_DELAY = max(1, int(os.getenv('AI_RETRY_BASE_DELAY', '10')))
AI_RETRY_MAX_DELAY = max(AI_RETRY_BASE_DELAY, int(os.getenv('AI_RETRY_MAX_DELAY', '3600')))
GROQ_RPM_LIMIT = max(1, int(os.getenv('GROQ_RPM_LIMIT', '30')))
GROQ_RPD_LIMIT = max(1, int(os.getenv('GROQ_RPD_LIMIT', '1000')))
GROQ_TPM_LIMIT = max(256, int(os.getenv('GROQ_TPM_LIMIT', '8000')))
GROQ_TPD_LIMIT = max(256, int(os.getenv('GROQ_TPD_LIMIT', '200000')))
AI_WORKER_LEASE_SECONDS = max(AI_REQUEST_TIMEOUT + 60,
                              int(os.getenv('AI_WORKER_LEASE_SECONDS', str(max(300, AI_REQUEST_TIMEOUT + 60)))))
AI_MAX_ACTIVE_JOBS_PER_USER = max(1, int(os.getenv('AI_MAX_ACTIVE_JOBS_PER_USER', '1')))
AI_INPUT_COST_PER_MILLION = os.getenv('AI_INPUT_COST_PER_MILLION', '').strip() or None
AI_OUTPUT_COST_PER_MILLION = os.getenv('AI_OUTPUT_COST_PER_MILLION', '').strip() or None
if AI_INPUT_COST_PER_MILLION is not None:
    from decimal import Decimal
    AI_INPUT_COST_PER_MILLION = Decimal(AI_INPUT_COST_PER_MILLION)
if AI_OUTPUT_COST_PER_MILLION is not None:
    from decimal import Decimal
    AI_OUTPUT_COST_PER_MILLION = Decimal(AI_OUTPUT_COST_PER_MILLION)
PRIVATE_DOCUMENT_ROOT = Path(os.getenv('PRIVATE_DOCUMENT_ROOT', str(BASE_DIR / 'private_documents')))
MAX_RESEARCH_UPLOAD_BYTES = int(os.getenv('MAX_RESEARCH_UPLOAD_BYTES', str(25 * 1024 * 1024)))
SIMILARITY_MIN_PASSAGE_WORDS = max(3, int(os.getenv('SIMILARITY_MIN_PASSAGE_WORDS', '8')))
SIMILARITY_NEAR_THRESHOLD = min(1.0, max(0.5, float(os.getenv('SIMILARITY_NEAR_THRESHOLD', '0.82'))))
SIMILARITY_SHINGLE_SIZE = max(2, int(os.getenv('SIMILARITY_SHINGLE_SIZE', '5')))
SIMILARITY_MAX_TARGET_VERSIONS = max(1, min(20, int(os.getenv('SIMILARITY_MAX_TARGET_VERSIONS', '10'))))
SIMILARITY_MAX_DOCUMENT_WORDS = max(1000, int(os.getenv('SIMILARITY_MAX_DOCUMENT_WORDS', '100000')))
SIMILARITY_WORKER_LEASE_SECONDS = max(60, int(os.getenv('SIMILARITY_WORKER_LEASE_SECONDS', '900')))
CITATION_MAX_REFERENCES = max(25, min(5000, int(os.getenv('CITATION_MAX_REFERENCES', '1500'))))
CITATION_PROVIDER_TIMEOUT = max(2, min(20, int(os.getenv('CITATION_PROVIDER_TIMEOUT', '8'))))
CITATION_PROVIDER_MAX_RESPONSE_BYTES = max(16384, min(2_000_000, int(os.getenv('CITATION_PROVIDER_MAX_RESPONSE_BYTES', '500000'))))
CITATION_MAX_METADATA_LOOKUPS = max(1, min(200, int(os.getenv('CITATION_MAX_METADATA_LOOKUPS', '50'))))
CITATION_METADATA_ENABLED = os.getenv('CITATION_METADATA_ENABLED', 'true').lower() == 'true'
CROSSREF_MAILTO = os.getenv('CROSSREF_MAILTO', '').strip()
OPENALEX_API_KEY = os.getenv('OPENALEX_API_KEY', '').strip()
JOURNAL_PROVIDER_TIMEOUT = max(2, min(20, int(os.getenv('JOURNAL_PROVIDER_TIMEOUT', '8'))))
JOURNAL_MAX_RESULTS = max(5, min(50, int(os.getenv('JOURNAL_MAX_RESULTS', '20'))))
JOURNAL_RETRY_LIMIT = max(0, min(5, int(os.getenv('JOURNAL_RETRY_LIMIT', '3'))))
DOCUMENT_PROCESSING_STALE_SECONDS = max(60, min(86400, int(os.getenv('DOCUMENT_PROCESSING_STALE_SECONDS', '900'))))
CACHES = {
    'default': ({'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': REDIS_URL}
                if REDIS_URL else {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'scholivyn-auth-limits'})
}
LANGUAGE_CODE='en-us'; TIME_ZONE='Asia/Kolkata'; USE_I18N=True; USE_TZ=True
STATIC_URL='static/'; DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
