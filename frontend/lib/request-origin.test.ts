import { afterEach, describe, expect, it, vi } from 'vitest';
import { isAllowedRequestOrigin } from './request-origin';

function request(origin?: string, host?: string, forwardedHost?: string) {
  const headers = new Headers();
  if (origin !== undefined) headers.set('origin', origin);
  if (host !== undefined) headers.set('host', host);
  if (forwardedHost !== undefined) headers.set('x-forwarded-host', forwardedHost);
  return { headers };
}

describe('BFF request origin validation', () => {
  afterEach(() => vi.unstubAllEnvs());

  it.each([
    ['http://localhost:3000', 'localhost:3000'],
    ['http://localhost:3001', 'localhost:3001'],
    ['http://127.0.0.1:3000', '127.0.0.1:3000'],
    ['http://127.0.0.1:3001', '127.0.0.1:3001'],
  ])('allows explicit local development origin %s', (origin, host) => {
    vi.stubEnv('NODE_ENV', 'development');
    expect(isAllowedRequestOrigin(request(origin, host))).toBe(true);
  });

  it('rejects untrusted, missing, null, malformed, and mismatched origins', () => {
    vi.stubEnv('NODE_ENV', 'development');
    expect(isAllowedRequestOrigin(request('https://evil.example', 'evil.example'))).toBe(false);
    expect(isAllowedRequestOrigin(request(undefined, 'localhost:3000'))).toBe(false);
    expect(isAllowedRequestOrigin(request('null', 'localhost:3000'))).toBe(false);
    expect(isAllowedRequestOrigin(request('not-an-origin', 'localhost:3000'))).toBe(false);
    expect(isAllowedRequestOrigin(request('http://localhost:3000/path', 'localhost:3000'))).toBe(false);
    expect(isAllowedRequestOrigin(request('http://localhost:3000', 'evil.example'))).toBe(false);
  });

  it('does not trust forwarded-host to override the browser Host', () => {
    vi.stubEnv('NODE_ENV', 'development');
    expect(isAllowedRequestOrigin(request('http://localhost:3000', 'evil.example', 'localhost:3000'))).toBe(false);
  });

  it('uses only the explicitly configured production origin', () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('PUBLIC_APP_ORIGIN', 'https://app.scholivyn.example');
    expect(isAllowedRequestOrigin(request('https://app.scholivyn.example', 'app.scholivyn.example'))).toBe(true);
    expect(isAllowedRequestOrigin(request('http://localhost:3000', 'localhost:3000'))).toBe(false);
    expect(isAllowedRequestOrigin(request('https://evil.example', 'evil.example', 'app.scholivyn.example'))).toBe(false);
  });

  it('fails closed in production when the public origin is missing or malformed', () => {
    vi.stubEnv('NODE_ENV', 'production');
    vi.stubEnv('PUBLIC_APP_ORIGIN', '');
    expect(isAllowedRequestOrigin(request('https://app.scholivyn.example', 'app.scholivyn.example'))).toBe(false);
    vi.stubEnv('PUBLIC_APP_ORIGIN', 'https://app.scholivyn.example/path');
    expect(isAllowedRequestOrigin(request('https://app.scholivyn.example', 'app.scholivyn.example'))).toBe(false);
  });
});
