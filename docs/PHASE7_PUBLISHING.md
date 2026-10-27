# Phase 7 — Journal discovery and publishing guidance

## Scope and safety

Journal discovery compares the metadata inferred from one completed, immutable `DocumentVersion` with journal records returned by OpenAlex Sources and Crossref Journals. External lookup is user initiated and requires explicit consent. The backend sends only a bounded query derived from title, research field, keywords, and inferred topics (maximum 250 characters); it does not send the abstract, manuscript text, user identity, or private document path. Provider credentials, if configured, stay server-side. The app does not submit manuscripts, contact editors, or claim acceptance probability.

OpenAlex provides source-level journal metadata including identifiers, subject topics, OA/DOAJ indicators, and works counts ([Sources](https://help.openalex.org/data/sources/), [API endpoints](https://help.openalex.org/api/endpoints/)). Crossref's REST API exposes journal metadata and ISSN lookup ([Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)). These are provider-reported fields, not independent verification of journal legitimacy. DOAJ is not queried directly: any DOAJ indicator in this implementation is the OpenAlex-reported value. No web scraping, acceptance-rate, impact-factor, APC, indexing, review-time, or external coverage claims are made.

## Data model and retention

- `ManuscriptProfile` is unique per owner and document version. Automated fields and user corrections are stored separately; profiling never edits source extraction or manuscripts.
- `JournalRecommendationJob` is owner- and idempotency-key scoped. External consent and the version-pinned profile are retained with the job.
- `JournalMetadataSnapshot` stores the provider's dated response. Snapshots referenced by jobs, saves, or submission prep are protected from deletion. Provider records are scoped to jobs via their relationship, preventing one user's search results from leaking through shared catalog rows.
- Readiness assessments and submission drafts are owner/version scoped. The cover letter is an editable template with visible placeholders and no presumed ethics, novelty, funding, exclusivity, or author-consent statements.
- Project/user deletion behavior follows the existing owner cascade and `PROTECT` relationships for versioned publishing history. Administrators should review dependent records before deleting a source version.

## Ranking methodology

The deterministic suitability score uses available evidence only and renormalizes weights over available components:

| Component | Weight |
| --- | ---: |
| Jaccard overlap of manuscript keywords/topics with provider subject terms | 50% |
| Research-field text relevance | 25% |
| Presence of provider-reported works activity | 15% |
| Open-access preference, only when requested and provider data exists | 10% |

Unknown evidence is omitted and weights are renormalized; no unavailable values are treated as negative. Scores are not calibrated probabilities and do not predict acceptance. ISSNs are checksum-validated; cross-provider agreement or discrepancies are shown as evidence, not a guarantee of a journal's legitimacy. Missing or conflicting data requires human verification against the publisher's official journal site and current instructions.

## API and processing

Authenticated endpoints are under `/api/v1/publishing/`:

- `profiles/` and `profiles/{id}/` — profile a completed owned version and save bounded user corrections.
- `recommendations/` — owner history; POST creates an idempotent, consent-gated Celery job.
- `recommendations/{uuid}/` and `.../actions/{cancel|retry}/` — owner-only status/actions.
- `saved-journals/` — save and remove items only from the user's own recommendation history.
- `readiness/` and `readiness/{id}/report/` — version-pinned checklist and owner-authorized PDF.
- `submissions/` — editable cover-letter/checklist preparation only; no journal submission occurs.

The Celery task runs on the existing `celery` queue. It checkpoints each provider, keeps bounded retries, uses a lease/watchdog for recovery, and skips providers already completed after a retry. Provider requests have a timeout, fixed HTTPS host allowlist, no redirects, bounded response size, cached responses, safe error categories, and a short request spacing guard.

## Configuration and local rollout

Optional environment values (no credentials are required for Crossref):

```dotenv
OPENALEX_API_KEY=
JOURNAL_PROVIDER_TIMEOUT=8
JOURNAL_MAX_RESULTS=20
JOURNAL_RETRY_LIMIT=3
```

The optional OpenAlex key is server-only. Do not add it to any `NEXT_PUBLIC_*` variable. The example file intentionally contains no secrets.

This feature adds migration `publishing.0001_initial`. Review the migration and take the normal verified backup before applying it to a chosen local/staging database. It is deliberately not auto-applied by this implementation. Check state first with `python manage.py showmigrations publishing`, then apply only by explicit operator decision using `python manage.py migrate publishing` after reviewing the database target and backup.

Run backend tests with `python manage.py test apps.publishing.tests`; no real external provider calls are needed. Provider adapters are mocked in tests. Confirm the Celery worker includes the existing `celery` queue before testing an explicitly consented user search.

## Remaining limitations

- Provider metadata may be stale, incomplete, or incorrect; identity evidence does not constitute accreditation or legitimacy verification.
- Search ranking has no acceptance-rate, impact-factor, APC, indexing, scope-policy, or review-time inference.
- Journal-specific submission instructions have not been independently validated or imported; readiness entries are general prompts, not compliance decisions.
- The current readiness PDF exports the checklist; the frontend submission draft remains user-editable and is not sent externally.
- External provider production availability and Celery recovery require separate staging verification. Unit tests intentionally do not contact providers.
