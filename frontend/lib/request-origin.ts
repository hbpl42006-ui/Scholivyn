import type { NextRequest } from 'next/server';

/**
 * Validate the browser-facing origin and Host, not Next's reconstructed URL
 * (which may reflect the container's internal port behind Docker publishing).
 * Forwarded headers are intentionally ignored: only trust them when a proxy
 * boundary is explicitly configured and enforced.
 */
export function isAllowedRequestOrigin(req: Pick<NextRequest, 'headers'>): boolean {
  const originHeader = req.headers.get('origin');
  const hostHeader = req.headers.get('host');
  if (!originHeader || !hostHeader || originHeader === 'null') return false;

  try {
    const origin = new URL(originHeader);
    // Origin headers are serialized origins, not arbitrary URLs. Reject paths,
    // credentials, query strings, fragments, and non-HTTP(S) schemes.
    if (originHeader !== origin.origin || !['http:', 'https:'].includes(origin.protocol)) return false;

    const requestHost = hostHeader.trim().toLowerCase();
    if (!requestHost || requestHost !== origin.host.toLowerCase()) return false;

    if (process.env.NODE_ENV !== 'production') {
      // Local development runs on either frontend port and may be opened via
      // either loopback hostname. Keep this an explicit, finite allowlist.
      return new Set([
        'http://localhost:3000',
        'http://localhost:3001',
        'http://127.0.0.1:3000',
        'http://127.0.0.1:3001',
      ]).has(origin.origin);
    }

    // Production must have an explicit public origin; never fall back to a
    // localhost default. Forwarded headers are not trusted here.
    const configuredOrigin = process.env.PUBLIC_APP_ORIGIN;
    if (!configuredOrigin) return false;
    const expected = new URL(configuredOrigin);
    return configuredOrigin === expected.origin && origin.origin === expected.origin;
  } catch {
    return false;
  }
}
