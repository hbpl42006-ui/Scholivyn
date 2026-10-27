# Production security configuration

Scholivyn keeps native Windows development on plain HTTP. With `DEBUG=True`,
SSL redirects, secure-only cookies, and HSTS default off. The clickjacking
middleware and non-sniffing/referrer headers are safe in both environments.

For production, inject secrets through the hosting platform's secret manager
or protected process environment (never a committed `.env`):

- `DEBUG=False`
- `SECRET_KEY`: the existing Django key, at least 50 characters with high
  entropy.
- `JWT_SIGNING_KEY`: the existing JWT signing key, at least 32 characters.
  If it has historically defaulted to `SECRET_KEY`, preserve that exact value
  during rollout. Changing it invalidates active JWTs; rotate only with an
  explicit re-authentication plan.
- `ALLOWED_HOSTS`: comma-separated exact public hostnames; wildcards are
  rejected in production.
- `CSRF_TRUSTED_ORIGINS`: comma-separated HTTPS origins when cross-origin admin
  or browser requests require them.
- `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and
  `SECURE_HSTS_SECONDS` can be explicitly set for the TLS topology. Secure
  defaults activate when `DEBUG=False`; HSTS defaults to one year. Enable
  `SECURE_HSTS_INCLUDE_SUBDOMAINS` or `SECURE_HSTS_PRELOAD` only after verifying
  every affected hostname supports HTTPS.

When TLS terminates at a reverse proxy, configure the proxy to overwrite and
sanitize forwarded headers. Do not set `SECURE_PROXY_SSL_HEADER` or trust
forwarded host headers unless that proxy boundary is controlled and verified.
The Windows `.env` loader intentionally imports only AI development settings;
it does not load Django/JWT/email/database secrets.

The ignored `backend/jwt-signing-key.local` file is not automatically loaded.
That preserves the currently active signing behavior and avoids an accidental
session-invalidating key switch. Inspect the file only through an approved
secret-management workflow; do not print or commit it.

## Native Windows development

From `F:\Scholivyn\backend`, with Redis available on localhost:

```powershell
$env:DEBUG = 'True'
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

In a second PowerShell window:

```powershell
cd F:\Scholivyn\backend
$env:DEBUG = 'True'
.\venv\Scripts\celery.exe -A config worker -Q celery,ai -P solo -l INFO
```

Run the frontend separately with its existing npm development command. No HTTPS
redirect or secure-cookie-only setting is enabled for local HTTP.
