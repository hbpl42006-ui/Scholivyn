'use client';

import { useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { ApiError, authRequest } from '@/lib/auth';
import { AuthShell, Field } from '@/components/auth-shell';

type VerificationState = 'loading' | 'verified' | 'already_verified' | 'expired' | 'error';

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : 'We could not verify this link. Please try again.';
}

export function VerifyEmailStatus() {
  const params = useSearchParams();
  const router = useRouter();
  const uid = params.get('uid');
  const token = params.get('token');
  const [state, setState] = useState<VerificationState>('loading');
  const [message, setMessage] = useState('Verifying your email address…');
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [resendMessage, setResendMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => { void fetch('/api/auth/csrf', { credentials: 'same-origin' }); }, []);
  useEffect(() => {
    if (!uid || !token) {
      queueMicrotask(() => { setMessage('This verification link is incomplete. It may have expired or been copied incorrectly.'); setState('error'); });
      return;
    }
    let live = true;
    authRequest<{ detail: string; status?: string }>('verify-email', { uid, token })
      .then((result) => {
        if (!live) return;
        setMessage(result.detail);
        setState(result.status === 'already_verified' ? 'already_verified' : 'verified');
      })
      .catch((cause: unknown) => {
        if (live) {
          const detail = messageOf(cause);
          setMessage(detail);
          setState(detail.toLowerCase().includes('expired') ? 'expired' : 'error');
        }
      });
    return () => { live = false; };
  }, [uid, token]);
  useEffect(() => {
    if (state !== 'verified' && state !== 'already_verified') return;
    const timer = window.setTimeout(() => router.replace('/login?verified=1'), 1800);
    return () => window.clearTimeout(timer);
  }, [router, state]);
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((seconds) => seconds - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); setResendMessage('');
    try {
      const result = await authRequest<{ detail: string }>('verify-email/resend', { email });
      setResendMessage(result.detail); setCooldown(60);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.status === 429 ? 'Too many requests. Please wait before trying again.' : messageOf(cause));
      if (cause instanceof ApiError && cause.status === 429) setCooldown(60);
    } finally { setBusy(false); }
  }

  const complete = state === 'verified' || state === 'already_verified';
  const failed = state === 'error' || state === 'expired';
  return <AuthShell
    title={state === 'verified' ? 'Email verified' : state === 'already_verified' ? 'Already verified' : state === 'expired' ? 'Verification link expired' : state === 'error' ? 'Invalid verification link' : 'Email verification'}
    description={state === 'verified' ? 'Your account is active and ready to use.' : state === 'already_verified' ? 'Your account is active. Taking you to sign in…' : 'Confirm your email address to activate your account.'}
    footer={<Link href="/login" className="font-semibold text-blue-700 hover:underline">Back to login</Link>}
  >
    <div className="space-y-5">
      <p role="status" className={`rounded-lg px-4 py-3 text-sm leading-6 ${failed ? 'bg-red-50 text-red-800' : 'bg-teal-50 text-teal-900'}`}>{message}</p>
      {complete ? <Link href="/login?verified=1" className="flex w-full justify-center rounded-lg bg-[#2563eb] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600">Continue to sign in</Link> : (state === 'error' || state === 'expired') ? <>
        <p className="text-sm leading-6 text-slate-600">{state === 'expired' ? 'This link has expired.' : 'This link is invalid or incomplete.'} Request a fresh verification email below.</p>
        <form onSubmit={resend} className="space-y-4">
          {resendMessage && <p role="status" className="rounded-lg bg-teal-50 px-4 py-3 text-sm text-teal-900">{resendMessage}</p>}
          {error && <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}
          <Field label="Account email" name="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required />
          <button disabled={busy || cooldown > 0} className="w-full rounded-lg bg-[#2563eb] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-700">
            {busy ? 'Sending…' : cooldown ? `Try again in ${cooldown}s` : 'Send a new verification link'}
          </button>
        </form>
      </> : null}
    </div>
  </AuthShell>;
}
