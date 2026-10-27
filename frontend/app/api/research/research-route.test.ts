import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';
import { GET, POST } from './[...path]/route';

describe('research BFF boundary', () => {
  it('only proxies the research resource families', async () => {
    const req = new NextRequest('http://localhost:3001/api/research/auth/me');
    const response = await GET(req, { params: Promise.resolve({ path: ['auth', 'me'] }) });
    expect(response.status).toBe(404);
  });

  it('allows analysis resources through the authenticated BFF boundary', async () => {
    const req = new NextRequest('http://localhost:3001/api/research/analyses', {
      method: 'POST', headers: { host: 'localhost:3001', origin: 'http://localhost:3001' }, body: '{}',
    });
    const response = await POST(req, { params: Promise.resolve({ path: ['analyses'] }) });
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: 'CSRF validation failed. Refresh and try again.' });
  });

  it('allows similarity resources only through the same CSRF-protected boundary', async () => {
    const req = new NextRequest('http://localhost:3001/api/research/similarity', {
      method: 'POST', headers: { host: 'localhost:3001', origin: 'http://localhost:3001' }, body: '{}',
    });
    const response = await POST(req, { params: Promise.resolve({ path: ['similarity'] }) });
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: 'CSRF validation failed. Refresh and try again.' });
  });

  it('requires same-origin CSRF protection on state-changing uploads', async () => {
    const req = new NextRequest('http://localhost:3001/api/research/projects/abc/documents/upload', {
      method: 'POST', headers: { host: 'localhost:3001', origin: 'http://localhost:3001', 'content-type': 'multipart/form-data; boundary=x' }, body: '--x--\r\n',
    });
    const response = await POST(req, { params: Promise.resolve({ path: ['projects', 'abc', 'documents', 'upload'] }) });
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: 'CSRF validation failed. Refresh and try again.' });
  });
});
