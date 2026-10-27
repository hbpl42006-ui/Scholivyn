import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';
import { cookies } from 'next/headers';
import { GET, POST } from './route';

vi.mock('next/headers', () => ({ cookies: vi.fn() }));

function mockSession(access?: string) {
  vi.mocked(cookies).mockResolvedValue({
    get: (name: string) => name === 'scholivyn_access' && access ? { name, value: access } : undefined,
  } as Awaited<ReturnType<typeof cookies>>);
}

function request(origin?: string, host = 'localhost:3000', cookie = 'scholivyn_access=test-access; scholivyn_csrf=csrf-test', csrf = 'csrf-test') {
  const headers = new Headers({ 'content-type': 'application/json', cookie, 'x-csrf-token': csrf });
  if (origin !== undefined) headers.set('origin', origin);
  headers.set('host', host);
  return new NextRequest('http://localhost:3000/api/research/projects/', {
    method: 'POST', headers, body: JSON.stringify({ title: 'Isolated test project' }),
  });
}

describe('research BFF project creation origin and authentication', () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

  it.each([
    ['http://localhost:3000', 'localhost:3000'],
    ['http://localhost:3001', 'localhost:3001'],
    ['http://127.0.0.1:3000', '127.0.0.1:3000'],
    ['http://127.0.0.1:3001', '127.0.0.1:3001'],
  ])('forwards authenticated project creation from %s to Django', async (origin, host) => {
    vi.stubEnv('NODE_ENV', 'development');
    mockSession('test-access');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'isolated-project', title: 'Isolated test project' }), { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);
    const response = await POST(request(origin, host), { params: Promise.resolve({ path: ['projects'] }) });

    expect(response.status).toBe(201);
    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/v1/projects/');
    const forwarded = fetchMock.mock.calls[0][1] as RequestInit;
    expect(forwarded.method).toBe('POST');
    expect(new Headers(forwarded.headers).get('Authorization')).toBe('Bearer test-access');
    expect(forwarded.body).toBe(JSON.stringify({ title: 'Isolated test project' }));
  });

  it.each([undefined, 'invalid-origin', 'https://attacker.example'])('rejects missing or malformed/untrusted Origin %s before forwarding', async (origin) => {
    vi.stubEnv('NODE_ENV', 'development');
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const response = await POST(request(origin), { params: Promise.resolve({ path: ['projects'] }) });
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: 'Invalid request origin.' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects project creation without authenticated session or valid CSRF even on an allowed origin', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    mockSession();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Authentication credentials were not provided.' }), { status: 401 })));
    const noSession = await POST(request('http://localhost:3000', 'localhost:3000', 'scholivyn_csrf=csrf-test'), { params: Promise.resolve({ path: ['projects'] }) });
    expect(noSession.status).toBe(401);
    const badCsrf = await POST(request('http://localhost:3000', 'localhost:3000', 'scholivyn_access=test-access; scholivyn_csrf=csrf-test', 'wrong'), { params: Promise.resolve({ path: ['projects'] }) });
    expect(badCsrf.status).toBe(403);
  });

  it('allows the authenticated billing root through the same BFF session boundary', async () => {
    vi.stubEnv('NODE_ENV', 'development');
    mockSession('test-access');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ credits: 0 }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const req = new NextRequest('http://localhost:3000/api/research/billing/', {
      headers: { host: 'localhost:3000', cookie: 'scholivyn_access=test-access' },
    });
    const response = await GET(req, { params: Promise.resolve({ path: ['billing'] }) });
    expect(response.status).toBe(200);
    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8000/api/v1/billing/');
  });
});
