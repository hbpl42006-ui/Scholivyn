import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { isAllowedRequestOrigin } from '../../../../lib/request-origin';

const API = (process.env.DJANGO_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
const ACCESS_COOKIE = 'scholivyn_access';
const REFRESH_COOKIE = 'scholivyn_refresh';
const CSRF_COOKIE = 'scholivyn_csrf';
const secure = process.env.NODE_ENV === 'production';

function csrfToken() { return randomBytes(32).toString('hex'); }
function csrfValid(req: NextRequest) {
  const cookie = req.cookies.get(CSRF_COOKIE)?.value ?? '';
  const header = req.headers.get('x-csrf-token') ?? '';
  if (!cookie || !header || cookie.length !== header.length) return false;
  return timingSafeEqual(Buffer.from(cookie), Buffer.from(header));
}
function setSession(response: NextResponse, access: string, refresh: string) {
  response.cookies.set(ACCESS_COOKIE, access, { httpOnly: true, secure, sameSite: 'lax', path: '/', maxAge: 60 * 5 });
  response.cookies.set(REFRESH_COOKIE, refresh, { httpOnly: true, secure, sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 7 });
  response.cookies.set(CSRF_COOKIE, csrfToken(), { httpOnly: false, secure, sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 7 });
}
function clearSession(response: NextResponse) {
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE]) response.cookies.set(name, '', { httpOnly: name !== CSRF_COOKIE, secure, sameSite: 'lax', path: '/', maxAge: 0 });
}
async function django(path: string, body?: unknown, token?: string) {
  return fetch(`${API}/auth/${path}/`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    cache: 'no-store',
  });
}
async function jsonResponse(upstream: Response) {
  return NextResponse.json(await upstream.json().catch(() => ({})), { status: upstream.status });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ action: string[] }> }) {
  const { action } = await params;
  const route = action.join('/');
  if (route === 'csrf') {
    const response = NextResponse.json({ ok: true });
    if (!req.cookies.get(CSRF_COOKIE)) response.cookies.set(CSRF_COOKIE, csrfToken(), { httpOnly: false, secure, sameSite: 'lax', path: '/', maxAge: 60 * 60 * 24 * 7 });
    return response;
  }
  if (route !== 'me') return NextResponse.json({ detail: 'Not found.' }, { status: 404 });
  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  let upstream = access ? await django('me', undefined, access) : null;
  if ((!upstream || upstream.status === 401) && refresh) {
    const renewed = await django('refresh', { refresh });
    if (renewed.ok) {
      const tokens = await renewed.json();
      upstream = await django('me', undefined, tokens.access);
      const response = await jsonResponse(upstream);
      setSession(response, tokens.access, tokens.refresh ?? refresh);
      return response;
    }
  }
  if (!upstream) return NextResponse.json({ detail: 'Authentication required.' }, { status: 401 });
  const response = await jsonResponse(upstream);
  if (upstream.status === 401) clearSession(response);
  return response;
}

export async function POST(req: NextRequest, { params }: { params: Promise<{ action: string[] }> }) {
  const { action } = await params;
  const route = action.join('/');
  if (!isAllowedRequestOrigin(req)) return NextResponse.json({ detail: 'Invalid request origin.' }, { status: 403 });
  const payload = await req.json().catch(() => ({}));
  if (['register', 'verify-email', 'verify-email/resend', 'verify-email/change-email', 'password-reset', 'password-reset/confirm'].includes(route) && !csrfValid(req)) {
    return NextResponse.json({ detail: 'CSRF validation failed. Refresh and try again.' }, { status: 403 });
  }
  if (route === 'login') {
    const upstream = await django('login', payload);
    const body = await upstream.json().catch(() => ({}));
    if (!upstream.ok) return NextResponse.json(body, { status: upstream.status });
    const response = NextResponse.json({ ok: true });
    setSession(response, body.access, body.refresh);
    return response;
  }
  if (route === 'register') return jsonResponse(await django('register', payload));
  if (route === 'verify-email') return jsonResponse(await django('verify-email', payload));
  if (route === 'verify-email/resend' || route === 'verify-email/change-email') return jsonResponse(await django(route, payload));
  if (route === 'password-reset' || route === 'password-reset/confirm') return jsonResponse(await django(`${route}`, payload));
  if (route === 'refresh') {
    if (!csrfValid(req)) return NextResponse.json({ detail: 'CSRF validation failed.' }, { status: 403 });
    const jar = await cookies();
    const refresh = jar.get(REFRESH_COOKIE)?.value;
    if (!refresh) return NextResponse.json({ detail: 'Session expired.' }, { status: 401 });
    const upstream = await django('refresh', { refresh });
    const body = await upstream.json().catch(() => ({}));
    if (!upstream.ok) { const response = NextResponse.json(body, { status: upstream.status }); clearSession(response); return response; }
    const response = NextResponse.json({ ok: true });
    setSession(response, body.access, body.refresh ?? refresh);
    return response;
  }
  if (route === 'logout') {
    if (!csrfValid(req)) return NextResponse.json({ detail: 'CSRF validation failed.' }, { status: 403 });
    const response = NextResponse.json({ ok: true });
    clearSession(response);
    return response;
  }
  return NextResponse.json({ detail: 'Not found.' }, { status: 404 });
}
