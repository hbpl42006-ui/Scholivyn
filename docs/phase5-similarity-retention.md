# Phase 5 similarity retention policy

## Defaults

- Similarity reports have no automatic expiry. They remain available to their owner until explicitly deleted.
- `DELETE /api/v1/similarity/{job_id}/` deletes only the authenticated owner's report, comparisons, and match rows. It never deletes a manuscript or AI review. A subsequent detail or PDF request returns 404.
- Deleting a document or project first checks all pinned document versions. If owned similarity reports depend on them, the API returns HTTP 409 with the dependent report and version references. The client must ask for explicit confirmation and repeat the delete with `delete_dependent_similarity_reports: true`.
- The confirmation operation removes only dependent reports owned by the requester, and only in the same transaction as the requested document/project deletion. A dependency owned by a different account blocks deletion without disclosing that report.
- Historical AI analyses and writing suggestions are retained. Their project, document, and version references use `PROTECT`; a document/project with that history cannot be deleted through the application. This is intentional until a separately approved archival/export policy exists.
- Private uploaded files are removed only after the database transaction deleting their version commits. A rollback leaves the file intact.

## Migration and local application

Migration `intelligence.0005_protect_historical_review_sources` changes ORM deletion behavior only; it does not rewrite historical analysis data. It has been added but must be reviewed and applied using the project's normal migration procedure. Do not run migrations against an existing local database as part of verification without an explicit operator decision.

## Limits

Deleting a project removes its documents only when no protected AI history exists and every dependent similarity report owned by the requester was explicitly confirmed for removal. The app does not support deleting another user's report, force-deleting retained AI history, or automatic time-based retention.
