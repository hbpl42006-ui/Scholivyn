export type User = {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: 'student' | 'researcher' | 'professor' | 'admin';
  date_joined: string;
  is_staff?: boolean;
};

export function isProtectedRoute(pathname: string) {
  return pathname === '/dashboard' || pathname.startsWith('/dashboard/');
}

export class ApiError extends Error {
  status: number;
  fields?: Record<string, unknown>;
  retryAfterSeconds?: number;
  constructor(message: string, status: number, fields?: Record<string, unknown>, retryAfterSeconds?: number) {
    super(message);
    this.status = status;
    this.fields = fields;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export async function authRequest<T>(path: string, data?: unknown): Promise<T> {
  const readCsrf = () => typeof document === 'undefined'
    ? ''
    : document.cookie.split('; ').find((item) => item.startsWith('scholivyn_csrf='))?.split('=').slice(1).join('=') ?? '';
  let csrf = readCsrf();
  if (data !== undefined && !csrf) {
    await fetch('/api/auth/csrf', { credentials: 'same-origin' });
    csrf = readCsrf();
  }
  const response = await fetch(`/api/auth/${path}`, {
    method: data === undefined ? 'GET' : 'POST',
    credentials: 'same-origin',
    headers: {
      ...(data === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(data === undefined ? {} : { 'X-CSRF-Token': decodeURIComponent(csrf) }),
    },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fields = payload as Record<string, unknown>;
    const message = typeof fields.detail === 'string'
      ? fields.detail
      : Object.values(fields).flatMap((value) => Array.isArray(value) ? value : []).find((value) => typeof value === 'string') as string | undefined;
    throw new ApiError(message ?? 'Request could not be completed. Please try again.', response.status, payload as Record<string, unknown>);
  }
  return payload as T;
}
