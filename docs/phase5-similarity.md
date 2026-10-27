# Phase 5 — selected-source similarity

## Scope and interpretation

The similarity feature compares only the completed document versions explicitly selected by an authenticated owner. The shipped source provider reads stored extraction metadata for those versions; it does not crawl the web, query scholarly databases, or inspect other users' files. Similarity is not a plagiarism finding, proof of misconduct, or a substitute for institutional review. Citation/quotation labels are nearby textual signals, not citation verification. It is not equivalent to Turnitin.

## Algorithm and score

- Text comes from immutable `DocumentVersion.extraction_metadata` section paragraph records. Original text is not rewritten or changed.
- Token values are Unicode NFKC-normalized and case-folded, while offsets remain Unicode code-point offsets into the original extracted paragraph.
- Exact passages are detected from shared configurable word shingles and expanded to maximal contiguous exact token runs. Near-duplicate fallback uses deterministic shingle-set Jaccard similarity.
- Defaults: minimum passage 8 words, shingle width 5, near threshold 0.82. Settings: `SIMILARITY_MIN_PASSAGE_WORDS`, `SIMILARITY_SHINGLE_SIZE`, `SIMILARITY_NEAR_THRESHOLD`, `SIMILARITY_MAX_TARGET_VERSIONS`, and `SIMILARITY_MAX_DOCUMENT_WORDS`.
- Reference/bibliography sections are excluded from scanning and from the denominator. The displayed percentage is the union of matched source words divided by non-reference words in the selected source version, against only the user-selected target versions. Overlapping matches across targets are counted once. Exact and near-match counts are comparison/passage counts, so the same source span may occur in separate source comparisons while source coverage is unioned.
- The current citation label is heuristic: quotation marks or a nearby numeric/author-year citation pattern produce `quoted_or_cited`; otherwise it is `potentially_unattributed`. Neither label asserts misconduct.

## Data and endpoints

New tables: `similarity_similarityjob`, `similarity_similaritycomparison`, `similarity_similaritymatch`. Job and comparison records retain source/target `DocumentVersion` foreign keys; match rows retain section keys/titles, paragraph identifiers/indexes, original source offsets, and deterministic similarity/citation labels. Preview text is reconstructed from the version snapshot on authorized reads; private file paths are never serialized.

- `GET/POST /api/v1/similarity/` — history/create with owner checks and idempotency key.
- `GET /api/v1/similarity/{job_id}/` — status and selected-source results.
- `POST /api/v1/similarity/{job_id}/cancel/` and `/retry/` — owner-only lifecycle actions.
- `GET /api/v1/similarity/{job_id}/report/` — owner-only PDF after completion.

Jobs run on Celery's normal `celery` queue; they make no AI/provider calls. Completed per-target results are committed transactionally and skipped on redelivery/retry. A lease allows stale processing jobs to be reclaimed after worker loss. Existing project/version deletion is protected when referenced by an active or historical similarity job.

The `SimilaritySourceProvider` protocol is the extension boundary for future explicitly licensed source connectors. No external connector is implemented or advertised as available.

## Installation and local run

Do not apply the migration automatically during development setup. Back up the configured database first, then apply migrations explicitly to the intended database:

```powershell
cd F:\Scholivyn\backend
$env:SECRET_KEY = '<your existing local development secret>'
python manage.py migrate similarity
python manage.py runserver 127.0.0.1:8000
```

Run the existing local Redis and default Celery worker (not the AI queue worker) from separate PowerShell windows:

```powershell
cd F:\Scholivyn\backend
$env:SECRET_KEY = '<your existing local development secret>'
celery -A config worker -Q celery --pool=solo --loglevel=INFO
```

Frontend route: `/dashboard/similarity`. The UI selects completed versions from the user's existing projects, displays selected scope, and links to polling/results and PDF reporting.

Safe in-memory benchmark (does not use database, Redis, documents, or providers):

```powershell
python manage.py benchmark_similarity --words 5000
```

## Limitations

No external corpus or internet sources are searched. Normalized word shingles can miss translated, heavily paraphrased, OCR-damaged, or structurally altered reuse. Citations in metadata may be absent or misclassified. The engine is a reproducible similarity aid, not a plagiarism detector, originality guarantee, or legal/academic determination. Benchmark on representative, non-sensitive samples before setting production limits.
