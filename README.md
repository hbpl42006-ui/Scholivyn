# Scholivyn

Research Smarter. Publish Better.

Phase 1 foundation for an AI-assisted academic research workspace. The repository contains a Next.js frontend and Django REST API, with PostgreSQL, Redis and Celery-ready Docker services.

## Run locally

1. Copy `.env.example` to `.env`.
2. Start services: `docker compose up --build`.
3. Open the Docker frontend at [http://localhost:3001](http://localhost:3001) and the API at [http://localhost:8000/api/v1/](http://localhost:8000/api/v1/). Running `npm run dev` directly still uses Next.js's default port 3000 unless configured otherwise.

If Docker reports that it cannot connect to `dockerDesktopLinuxEngine`, start Docker Desktop and wait for its engine indicator to show **Running**, then retry the compose command. In PowerShell you can check with `docker info`. Docker Desktop is not required for local development: use SQLite for Django by unsetting `POSTGRES_HOST`, run the API with `python manage.py runserver`, and run the frontend with `npm install` followed by `npm run dev` in `frontend`.

The initial release includes the public marketing site, responsive dashboard shell, custom user model, registration/login endpoints, protected profile endpoint, API client, health endpoint and baseline tests. AI analysis, similarity, citations, billing and journal integrations remain intentionally unavailable until their providers are configured.

### Research intelligence (Phase 3)

AI manuscript review is disabled by default. Choose `AI_PROVIDER=openai` with `OPENAI_API_KEY`, or `AI_PROVIDER=gemini` with `GEMINI_API_KEY`; set `AI_MODEL` to a model available to that provider project and explicitly set `AI_ANALYSIS_ENABLED=true`. Gemini is supported through Google's official `google-genai` SDK (for example, `gemini-2.5-flash`). Never put provider credentials in `NEXT_PUBLIC_*` variables or frontend code. Restart the backend and `ai-worker` after configuration. The frontend requires explicit per-manuscript consent before sending extracted text to the configured provider. A missing key/model is reported as “AI analysis is not configured”; no sample or fabricated findings are returned.

On native Windows development, Django settings selectively load only AI-related variables from the repository-root `.env`; Docker-only entries such as `POSTGRES_HOST=db` and `REDIS_URL=redis://redis:6379/0` are not loaded by that local helper. Run Django with the local SQLite database and Redis at `127.0.0.1:6379`; see the PowerShell commands below. Docker Compose continues to inject the root `.env` into its containers as before.

For a first Gemini run, confirm the selected Google AI Studio project has access to the configured model and review its current billing, quota, and rate limits first. Use a short, isolated test manuscript with non-sensitive text, consent to provider processing, submit one analysis, and watch the existing analysis history for its result. Do not retry repeatedly on quota, billing, model-access, or authentication errors; resolve the provider-side issue first.

Analysis uses the dedicated Redis-backed `ai` queue. Analysis creation is limited by `AI_ANALYSIS_RATE` (3/hour by default), while analysis-history reads use the separate `AI_ANALYSIS_READ_RATE` (120/hour by default), so history polling does not spend creation quota. Processing is also capped by `AI_MAX_DOCUMENT_WORDS`, `AI_MAX_CHUNK_TOKENS`, `AI_MAX_OUTPUT_TOKENS`, and `AI_MAX_ACTIVE_JOBS_PER_USER`. Estimated cost is only recorded when both token-price environment settings are supplied; it is not provider billing. The generated PDF is built from persisted review rows at download time and is not stored as a public file.

For production, set a high-entropy `JWT_SIGNING_KEY` (for example, generate one with `python -c "import secrets; print(secrets.token_urlsafe(64))"`). The signing key falls back to `SECRET_KEY` only for compatibility. Rotating it invalidates existing JWT sessions, so plan re-authentication. API credentials and manuscript text must stay server-side.

### Native Windows: Django and Celery with Gemini

Install backend dependencies after adding `GEMINI_API_KEY`, `AI_PROVIDER=gemini`, `AI_MODEL=gemini-2.5-flash`, and `AI_ANALYSIS_ENABLED=true` to the root `.env`:

```powershell
Set-Location F:\Scholivyn\backend
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

In the Django terminal, force local SQLite and local Redis (rather than Docker service hostnames), then start the API:

```powershell
Set-Location F:\Scholivyn\backend
.\venv\Scripts\Activate.ps1
$env:POSTGRES_HOST = $null
$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
$env:CELERY_BROKER_URL = $env:REDIS_URL
$env:CELERY_RESULT_BACKEND = $env:REDIS_URL
python manage.py check
python manage.py runserver 127.0.0.1:8000
```

In a second PowerShell terminal, use the same local database and Redis settings and run one worker consuming both existing queues. The local AI allowlist is loaded from root `.env` by Django settings for both processes:

```powershell
Set-Location F:\Scholivyn\backend
.\venv\Scripts\Activate.ps1
$env:POSTGRES_HOST = $null
$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
$env:CELERY_BROKER_URL = $env:REDIS_URL
$env:CELERY_RESULT_BACKEND = $env:REDIS_URL
python -m celery -A config worker --loglevel=INFO -Q celery,ai --pool=solo
```

## Development

Frontend: `cd frontend && npm install && npm run dev`

Backend: `cd backend && python -m venv .venv && .venv\\Scripts\\activate && pip install -r requirements.txt && python manage.py migrate && python manage.py runserver`

### Email delivery

Local development keeps Django's console email backend: verification and password recovery messages appear in the backend terminal. Set `FRONTEND_URL` to the public frontend origin so generated action links point to the right host.

For SMTP delivery, configure these backend environment variables (never put SMTP credentials in frontend variables):

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.your-provider.example
EMAIL_PORT=587
EMAIL_HOST_USER=your-smtp-user
EMAIL_HOST_PASSWORD=your-smtp-password
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=Scholivyn <accounts@your-domain.example>
FRONTEND_URL=https://your-frontend-domain.example
```

Keep `EMAIL_USE_TLS` and `EMAIL_USE_SSL` mutually exclusive. For local secrets, store values only in your ignored `.env` file or your deployment secret manager. Rate limits use Redis when `REDIS_URL` is configured; they fall back to per-process memory for local development without Redis.

See `docs/ARCHITECTURE.md` and `docs/ROADMAP.md` for boundaries and next steps.
