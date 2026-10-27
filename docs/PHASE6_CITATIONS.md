# Phase 6 — Citation and research-integrity checks

## Scope and interpretation

Citation checking is version-pinned and deterministic. It extracts IEEE-style numeric citations and common APA author/year forms from stored section/paragraph extraction metadata, parses bibliography entries, reconciles keys, and flags structural issues. Offsets refer to the original paragraph string; paragraph IDs/indexes link back to the document viewer. It does not establish source authenticity, quality, plagiarism, fabrication, or misconduct. Parsing is heuristic and currently focuses on IEEE numeric and APA 7 author/year patterns; unsupported formats are identified rather than silently certified.

Optional Crossref/OpenAlex checks are user-initiated and require explicit consent. Only parsed reference metadata (DOI/title/author/year) is sent; manuscript body text is not. Provider records are candidates, never proof. Requests use fixed HTTPS hosts, response/time limits, caching/rate spacing, bounded scheduled retries, and sanitized error categories. Crossref `mailto` and OpenAlex credentials are server-side configuration only.

## Local configuration

From the repository root, set local AI-independent Django secrets in the current PowerShell session as required by your existing development setup; do not commit them. Preserve the SQLite `DATABASES` setting and the local Redis URL. Citation-specific options are:

```powershell
$env:CITATION_METADATA_ENABLED = 'true'
$env:CITATION_MAX_REFERENCES = '1500'
$env:CITATION_MAX_METADATA_LOOKUPS = '50'
$env:CITATION_PROVIDER_TIMEOUT = '8'
$env:CROSSREF_MAILTO = 'maintainer@example.org' # optional, recommended for polite Crossref use
$env:OPENALEX_API_KEY = '...'                    # optional; server-side only
```

The defaults are bounded. Do not put these secrets into frontend variables. Metadata providers are contacted only after a user checks the consent box.

## API and processing

- `GET/POST /api/v1/citations/jobs/` — owner-scoped history and idempotent creation from an extracted `document_version_id`.
- `GET/DELETE /api/v1/citations/jobs/{id}/` — owner-scoped detail/deletion.
- `GET /api/v1/citations/jobs/{id}/items/?kind=citations|references|matches|findings` — paginated results.
- `POST /api/v1/citations/jobs/{id}/actions/cancel|retry|verify-metadata/` — guarded actions; metadata verification requires explicit `{ "consent": true }`.
- `POST /api/v1/citations/jobs/{id}/findings/{finding_id}/decision/` — owner-scoped review annotation; does not edit manuscript text.
- `GET /api/v1/citations/jobs/{id}/report/` — authenticated PDF report.

Celery sends citation extraction and metadata tasks to the existing `celery` queue. Metadata lookup is scheduled between requests rather than sleeping in a worker. The task pins the exact `DocumentVersion`; `PROTECT` prevents deleting a version with citation history. Deleting a citation job removes only its own derived citation-check data, not the document or AI analysis history.

## Migrations and safe local rollout

The app introduces `apps.citations.0001_initial`. No migration was applied during implementation. Before applying it to an existing SQLite or PostgreSQL database, make a verified backup, inspect the selected `DATABASES` target and run `python manage.py showmigrations citations`. Apply deliberately with `python manage.py migrate citations` only after confirming the database target. A fresh database will receive the migration through the normal migration graph.

Start the existing local services without changing the database configuration:

```powershell
# backend
cd F:\Scholivyn\backend
python manage.py runserver 127.0.0.1:8000

# another PowerShell window; use the project's established local Redis URL
cd F:\Scholivyn\backend
celery -A config worker -l info -P solo -Q celery

# frontend
cd F:\Scholivyn\frontend
npm run dev
```

## Known limitations

- Citation parsing is regex/heuristic-based, not a full CSL parser; nested/complex citations, multilingual author naming conventions, footnotes, and unusual bibliography layouts may be missed.
- Registry coverage is limited to Crossref and OpenAlex, and a registry match does not certify correctness.
- Only selected APA/IEEE structural checks are implemented; the feature is not a complete style-guide conformance engine.
- Metadata requests are bounded by a per-job reference cap. Operational rate spacing across multiple workers depends on a shared Django cache backend; use the configured shared Redis cache in multi-worker environments.
- Live provider behavior, staging settings, production database migration, and real multi-worker Redis recovery require separate authorized operational verification.
