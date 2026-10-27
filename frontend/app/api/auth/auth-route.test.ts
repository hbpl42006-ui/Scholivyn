import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { POST } from './[...action]/route';

function request(path: string, csrf?: string, origin = 'http://localhost:3001', body = '{}', host = 'localhost:3001') {
  return new NextRequest(`http://localhost:3001/api/auth/${path}`, {
    method: 'POST',
    headers: {
      origin,
      host,
      'content-type': 'application/json',
      ...(csrf ? { cookie: `scholivyn_csrf=${csrf}`, 'x-csrf-token': csrf } : {}),
    },
    body,
  });
}

describe('auth BFF route security', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('forwards verification payload to Django using POST', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'verified' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const payload = { uid: 'encoded-uid', token: 'signed-token' };
    const response = await POST(request('verify-email', 'csrf-test-token', 'http://localhost:3001', JSON.stringify(payload)), {
      params: Promise.resolve({ action: ['verify-email'] }),
    });
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/auth/verify-email/', expect.objectContaining({
      method: 'POST', body: JSON.stringify(payload),
    }));
  });

  it('rejects logout without a valid CSRF token', async () => {
    const response = await POST(request('logout'), { params: Promise.resolve({ action: ['logout'] }) });
    expect(response.status).toBe(403);
  });

  it('clears the session cookies on logout', async () => {
    const response = await POST(request('logout', 'csrf-test-token'), { params: Promise.resolve({ action: ['logout'] }) });
    expect(response.status).toBe(200);
    const cookies = response.headers.getSetCookie().join(';');
    expect(cookies).toContain('scholivyn_access=');
    expect(cookies).toContain('scholivyn_refresh=');
    expect(cookies).toContain('Max-Age=0');
  });

  it('rejects requests with a foreign origin', async () => {
    const response = await POST(request('logout', 'csrf-test-token', 'https://example.com'), { params: Promise.resolve({ action: ['logout'] }) });
    expect(response.status).toBe(403);
  });

  it('forwards a configured localhost:3001 login and sets HTTP-only session cookies', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ access: 'test-access', refresh: 'test-refresh' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const response = await POST(request('login', undefined, 'http://localhost:3001', JSON.stringify({ username: 'test-user', password: 'test-password' })), {
      params: Promise.resolve({ action: ['login'] }),
    });

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8000/api/v1/auth/login/', expect.objectContaining({ method: 'POST' }));
    const cookies = response.headers.getSetCookie();
    expect(cookies.some((cookie) => cookie.startsWith('scholivyn_access=') && /HttpOnly/i.test(cookie))).toBe(true);
    expect(cookies.some((cookie) => cookie.startsWith('scholivyn_refresh=') && /HttpOnly/i.test(cookie))).toBe(true);
  });

  it('rejects a valid-looking origin if the Host is not the configured public host', async () => {
    const response = await POST(request('login', undefined, 'http://localhost:3001', '{}', 'evil.example'), {
      params: Promise.resolve({ action: ['login'] }),
    });
    expect(response.status).toBe(403);
  });

  it('rejects a state-changing request with no Origin header', async () => {
    const req = new NextRequest('http://localhost:3001/api/auth/login', {
      method: 'POST', headers: { host: 'localhost:3001', 'content-type': 'application/json' }, body: '{}',
    });
    const response = await POST(req, { params: Promise.resolve({ action: ['login'] }) });
    expect(response.status).toBe(403);
  });
});
