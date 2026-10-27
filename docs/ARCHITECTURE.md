# Architecture

The frontend is a thin Next.js App Router client. The Django API owns authentication, authorization and domain data. Provider integrations will live behind service adapters; no provider output is synthesized when a provider is unavailable.

## Boundaries

- `frontend/app`: routes and presentation.
- `backend/apps`: bounded Django domains, beginning with accounts.
- PostgreSQL: durable relational state.
- Redis/Celery: queued document and report work (next phase).

JWT access/refresh tokens are provided by SimpleJWT for the foundation. Before production, move refresh handling to secure HTTP-only cookies and add email verification, throttling and revocation storage.
