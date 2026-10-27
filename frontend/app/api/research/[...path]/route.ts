import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import { randomBytes, timingSafeEqual } from 'node:crypto';
import { isAllowedRequestOrigin } from '../../../../lib/request-origin';

const API = (process.env.DJANGO_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
const ACCESS = 'scholivyn_access';
const REFRESH = 'scholivyn_refresh';
const CSRF = 'scholivyn_csrf';
const secure = process.env.NODE_ENV === 'production';
type Context = { params: Promise<{ path: string[] }> };

function validCsrf(req: NextRequest) {
  const cookie = req.cookies.get(CSRF)?.value ?? '';
  const header = req.headers.get('x-csrf-token') ?? '';
  return Boolean(cookie && header && cookie.length === header.length && timingSafeEqual(Buffer.from(cookie), Buffer.from(header)));
}

function writeSession(response: NextResponse, access: string, refresh: string) {
  response.cookies.set(ACCESS, access, { httpOnly: true, secure, sameSite: 'lax', path: '/', maxAge: 300 });
  response.cookies.set(REFRESH, refresh, { httpOnly: true, secure, sameSite: 'lax', path: '/', maxAge: 604800 });
  response.cookies.set(CSRF, randomBytes(32).toString('hex'), { httpOnly: false, secure, sameSite: 'lax', path: '/', maxAge: 604800 });
}

async function forward(req: NextRequest, target: string, access?: string) {
  const headers = new Headers();
  const contentType = req.headers.get('content-type');
  if (contentType && !contentType.includes('multipart/form-data')) headers.set('Content-Type', contentType);
  if (access) headers.set('Authorization', `Bearer ${access}`);
  const cloned = req.clone();
  const body = ['GET', 'HEAD'].includes(req.method) ? undefined : contentType?.includes('multipart/form-data')
    ? await cloned.formData()
    : await cloned.text();
  return fetch(target, { method: req.method, headers, body: body as BodyInit | undefined, cache: 'no-store' });
}

async function handle(req: NextRequest, context: Context) {
  const origin = req.headers.get('origin');
  if ((origin && !isAllowedRequestOrigin(req)) || (!origin && req.method !== 'GET')) {
    return NextResponse.json({ detail: 'Invalid request origin.' }, { status: 403 });
  }
  if (req.method !== 'GET' && !validCsrf(req)) return NextResponse.json({ detail: 'CSRF validation failed. Refresh and try again.' }, { status: 403 });
  const { path } = await context.params;
  if (!path.length || !['projects', 'documents', 'analyses', 'similarity', 'citations', 'publishing', 'billing'].includes(path[0]) || path.some((part) => part === '.' || part === '..')) return NextResponse.json({ detail: 'Not found.' }, { status: 404 });
  const target = `${API}/${path.map(encodeURIComponent).join('/')}/${req.nextUrl.search}`;
  const jar = await cookies();
  const access = jar.get(ACCESS)?.value;
  let upstream = await forward(req, target, access);
  let renewed: { access: string; refresh?: string } | undefined;
  if (upstream.status === 401) {
    const refresh = jar.get(REFRESH)?.value;
    if (refresh) {
      const response = await fetch(`${API}/auth/refresh/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh }), cache: 'no-store',
      });
      if (response.ok) {
        const tokens = await response.json() as { access: string; refresh?: string };
        renewed = tokens;
        upstream = await forward(req, target, tokens.access);
      }
    }
  }
  const contentType = upstream.headers.get('content-type') ?? 'application/json';
  const response = new NextResponse(upstream.body, { status: upstream.status, headers: {
    'Content-Type': contentType,
    ...(upstream.headers.get('content-disposition') ? { 'Content-Disposition': upstream.headers.get('content-disposition')! } : {}),
    ...(upstream.headers.get('retry-after') ? { 'Retry-After': upstream.headers.get('retry-after')! } : {}),
    'Cache-Control': 'no-store',
  }});
  if (renewed?.access) writeSession(response, renewed.access, renewed.refresh ?? jar.get(REFRESH)?.value ?? '');
  if (upstream.status === 401 && !renewed) {
    response.cookies.set(ACCESS, '', { httpOnly: true, secure, sameSite: 'lax', path: '/', maxAge: 0 });
    response.cookies.set(REFRESH, '', { httpOnly: true, secure, sameSite: 'lax', path: '/', maxAge: 0 });
  }
  return response;
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
