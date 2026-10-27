import { afterEach, describe, expect, it, vi } from 'vitest';
import { authRequest } from './auth';

describe('authRequest', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('sends same-origin credentials and CSRF token for state-changing requests', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=csrf-value' });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await authRequest('logout', {});
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/logout', expect.objectContaining({
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-value' },
    }));
  });

  it('posts the verification UID and token unchanged as JSON', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=csrf-value' });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'verified' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const payload = { uid: 'encoded-uid', token: 'url-safe-token' };
    await authRequest('verify-email', payload);
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/verify-email', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-value' },
    }));
  });

  it('surfaces backend field validation errors', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=csrf-value' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ email: ['Enter a valid email address.'] }), { status: 400 })));
    await expect(authRequest('register', { email: 'bad' })).rejects.toMatchObject({ message: 'Enter a valid email address.', status: 400 });
  });
});
