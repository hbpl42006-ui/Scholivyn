'use client';

import { useEffect, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { ApiError, authRequest } from '@/lib/auth';
import { useAuth } from '@/components/auth-provider';
import { AuthShell, Field, SubmitButton } from '@/components/auth-shell';

function messageOf(error: unknown) { return error instanceof Error ? error.message : 'Something went wrong. Please try again.'; }

export function LoginForm() {
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const router = useRouter(); const params = useSearchParams();
  const { refreshUser } = useAuth();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); const values = Object.fromEntries(new FormData(event.currentTarget));
    try { await authRequest('login', { username: values.username, password: values.password }); await refreshUser(); const target = params.get('next'); router.replace(target?.startsWith('/dashboard') ? target : '/dashboard'); }
    catch (e) { setError(e instanceof ApiError && e.status === 401 ? 'We couldn’t sign you in. Check your username or email and password, and verify your email address if you just registered.' : messageOf(e)); } finally { setBusy(false); }
  }
  return <AuthShell title="Welcome back" description="Sign in to continue your research." footer={<>New to Scholivyn? <Link className="font-semibold text-blue-700 hover:underline" href="/register">Create an account</Link><span className="mx-2 text-slate-400">·</span><Link className="font-semibold text-blue-700 hover:underline" href="/verify-email">Resend verification email</Link></>}>
    <form className="space-y-5" onSubmit={submit}>{error && <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}<Field label="Username or email" name="username" autoComplete="username" required /><Field label="Password" name="password" type="password" autoComplete="current-password" required /><div className="-mt-2 text-right"><Link href="/forgot-password" className="text-sm font-medium text-blue-700 hover:underline">Forgot password?</Link></div><SubmitButton busy={busy}>Sign in</SubmitButton></form>
  </AuthShell>;
}

export function RegisterForm() {
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [done, setDone] = useState(false);
  const [registeredEmail, setRegisteredEmail] = useState('');
  const [resendMessage, setResendMessage] = useState('');
  const [resendError, setResendError] = useState('');
  const [resendBusy, setResendBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [changingEmail, setChangingEmail] = useState(false);
  const [changeMessage, setChangeMessage] = useState('');
  const [changeError, setChangeError] = useState('');
  useEffect(() => { void fetch('/api/auth/csrf', { credentials: 'same-origin' }); }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(''); const values = Object.fromEntries(new FormData(event.currentTarget));
    try { await authRequest('register', { full_name: values.full_name, username: values.username, email: values.email, password: values.password, role: values.role }); setRegisteredEmail(String(values.email)); setDone(true); }
    catch (e) { setError(messageOf(e)); } finally { setBusy(false); }
  }
  useEffect(() => { if (cooldown <= 0) return; const timer = window.setTimeout(() => setCooldown(cooldown - 1), 1000); return () => window.clearTimeout(timer); }, [cooldown]);
  async function resend() {
    setResendBusy(true); setResendMessage(''); setResendError('');
    try { const result = await authRequest<{ detail: string }>('verify-email/resend', { email: registeredEmail }); setResendMessage(result.detail); setCooldown(60); }
    catch (e) { setResendError(messageOf(e)); if (e instanceof Error && 'status' in e && (e as { status?: number }).status === 429) setCooldown(60); }
    finally { setResendBusy(false); }
  }
  async function changeEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setChangeMessage(''); setChangeError('');
    const values = Object.fromEntries(new FormData(event.currentTarget));
    try { const result = await authRequest<{ detail: string }>('verify-email/change-email', { username: values.username, password: values.password, new_email: values.new_email }); setRegisteredEmail(String(values.new_email)); setChangeMessage(result.detail); setChangingEmail(false); setCooldown(60); }
    catch (e) { setChangeError(messageOf(e)); }
  }
  return <AuthShell title={done ? 'Check your inbox' : 'Create your account'} description={done ? <>We sent a verification link to <strong className="break-all text-slate-800">{registeredEmail}</strong>. Verify your address to activate your account.</> : 'Set up your private research workspace.'} footer={<>Already have an account? <Link className="font-semibold text-blue-700 hover:underline" href="/login">Back to login</Link></>}>
    {done ? <div className="space-y-5"><p role="status" className="rounded-lg bg-teal-50 px-4 py-3 text-sm leading-6 text-teal-900">Open the verification email and follow its link. In local development, the message is printed in the Django server console.</p>
      {resendMessage && <p role="status" className="rounded-lg bg-teal-50 px-4 py-3 text-sm text-teal-900">{resendMessage}</p>}{resendError && <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800">{resendError}</p>}{changeMessage && <p role="status" className="rounded-lg bg-teal-50 px-4 py-3 text-sm text-teal-900">{changeMessage}</p>}{changeError && <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800">{changeError}</p>}
      <button type="button" disabled={resendBusy || cooldown > 0} onClick={resend} className="w-full rounded-lg bg-[#2563eb] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-700">{resendBusy ? 'Sending…' : cooldown ? `Resend available in ${cooldown}s` : 'Resend verification email'}</button>
      <button type="button" onClick={() => { setChangingEmail(!changingEmail); setChangeError(''); setChangeMessage(''); }} className="w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm font-semibold text-[#102a43] transition-colors hover:bg-slate-50">{changingEmail ? 'Cancel email change' : 'Change email address'}</button>
      {changingEmail && <form onSubmit={changeEmail} className="space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-sm leading-6 text-slate-600">Confirm your account password to update the unverified address.</p><Field label="Username" name="username" autoComplete="username" required /><Field label="Password" name="password" type="password" autoComplete="current-password" required /><Field label="New email" name="new_email" type="email" autoComplete="email" required /><button className="w-full rounded-lg bg-[#102a43] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-slate-800">Update email and send link</button></form>}
      <div className="text-center text-sm"><Link className="font-medium text-blue-700 hover:underline" href="/login">Back to login</Link></div>
    </div> : <form className="space-y-4" onSubmit={submit}>{error && <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}<Field label="Full name" name="full_name" autoComplete="name" required /><Field label="Username" name="username" autoComplete="username" minLength={3} required /><Field label="Email" name="email" type="email" autoComplete="email" required /><Field label="Password" name="password" type="password" autoComplete="new-password" minLength={8} required /><label className="block text-sm font-medium text-slate-700">I am a<select name="role" className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3.5 py-3 text-sm outline-none focus:border-blue-500 focus:ring-4 focus:ring-blue-100"><option value="student">Student</option><option value="researcher">Researcher</option><option value="professor">Professor</option></select></label><SubmitButton busy={busy}>Create account</SubmitButton></form>}
  </AuthShell>;
}

export function ForgotPasswordForm() {
  const [busy, setBusy] = useState(false); const [sent, setSent] = useState(false); const [error, setError] = useState('');
  useEffect(() => { void fetch('/api/auth/csrf', { credentials: 'same-origin' }); }, []);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setError(''); try { await authRequest('password-reset', { email: new FormData(event.currentTarget).get('email') }); setSent(true); } catch (e) { setError(messageOf(e)); } finally { setBusy(false); } }
  return <AuthShell title="Reset your password" description="Enter your account email and we’ll send a secure reset link." footer={<Link href="/login" className="font-semibold text-blue-700 hover:underline">Back to sign in</Link>}>
    {sent ? <p role="status" className="rounded-lg bg-teal-50 px-4 py-3 text-sm leading-6 text-teal-800">If an active account matches that email, a reset link has been sent.</p> : <form className="space-y-5" onSubmit={submit}>{error && <p role="alert" className="text-sm text-red-700">{error}</p>}<Field label="Email" name="email" type="email" autoComplete="email" required /><SubmitButton busy={busy}>Send reset link</SubmitButton></form>}
  </AuthShell>;
}

export function ResetPasswordForm() {
  const params = useSearchParams(); const [busy, setBusy] = useState(false); const [done, setDone] = useState(false); const [error, setError] = useState('');
  useEffect(() => { void fetch('/api/auth/csrf', { credentials: 'same-origin' }); }, []);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setError(''); const password = new FormData(event.currentTarget).get('password'); try { await authRequest('password-reset/confirm', { uid: params.get('uid'), token: params.get('token'), new_password: password }); setDone(true); } catch (e) { setError(messageOf(e)); } finally { setBusy(false); } }
  return <AuthShell title={done ? 'Password updated' : 'Choose a new password'} description="Use at least eight characters for your new password." footer={<Link href="/login" className="font-semibold text-blue-700 hover:underline">Back to sign in</Link>}>
    {done ? <p role="status" className="rounded-lg bg-teal-50 px-4 py-3 text-sm text-teal-800">Your password has been updated. You can sign in now.</p> : <form className="space-y-5" onSubmit={submit}>{error && <p role="alert" className="text-sm text-red-700">{error}</p>}<Field label="New password" name="password" type="password" minLength={8} autoComplete="new-password" required /><SubmitButton busy={busy}>Update password</SubmitButton></form>}
  </AuthShell>;
}

export function VerifyEmailStatus() {
  const params = useSearchParams(); const [status, setStatus] = useState('Verifying your email…'); const [state, setState] = useState<'loading' | 'success' | 'error'>('loading'); const [resendEmail, setResendEmail] = useState(''); const [resending, setResending] = useState(false); const [resendMessage, setResendMessage] = useState(''); const [resendError, setResendError] = useState(''); const [cooldown, setCooldown] = useState(0);
  useEffect(() => { void fetch('/api/auth/csrf', { credentials: 'same-origin' }); }, []);
  const uid = params.get('uid'); const token = params.get('token');
  useEffect(() => { if (state !== 'error' || cooldown <= 0) return; const timer = window.setTimeout(() => setCooldown(cooldown - 1), 1000); return () => window.clearTimeout(timer); }, [cooldown, state]);
  useEffect(() => { if (!uid || !token) { queueMicrotask(() => { setStatus('This verification link is incomplete. It may have expired or been copied incorrectly.'); setState('error'); }); return; } let live = true; authRequest<{ detail: string }>('verify-email', { uid, token }).then((result) => { if (live) { setStatus(result.detail); setState('success'); } }).catch((e: unknown) => { if (live) { setStatus(messageOf(e)); setState('error'); } }); return () => { live = false; }; }, [uid, token]);
  async function resend(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setResending(true); setResendError(''); setResendMessage(''); try { const result = await authRequest<{ detail: string }>('verify-email/resend', { email: resendEmail }); setResendMessage(result.detail); setCooldown(60); } catch (e) { setResendError(messageOf(e)); if (e instanceof Error && 'status' in e && (e as { status?: number }).status === 429) setCooldown(60); } finally { setResending(false); } }
  return <AuthShell title={state === 'success' ? 'Email verified' : state === 'error' ? 'Verification link unavailable' : 'Email verification'} description={state === 'success' ? 'Your account is active and ready to use.' : 'Confirm your email address to activate your account.'} footer={<Link href="/login" className="font-semibold text-blue-700 hover:underline">Back to login</Link>}>
    <div className="space-y-5"><p role="status" className={`rounded-lg px-4 py-3 text-sm leading-6 ${state === 'error' ? 'bg-red-50 text-red-800' : 'bg-teal-50 text-teal-900'}`}>{status}</p>{state === 'success' ? <Link href="/login" className="flex w-full justify-center rounded-lg bg-[#2563eb] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700">Continue to sign in</Link> : state === 'error' ? <><p className="text-sm leading-6 text-slate-600">Verification links expire. Request a fresh link using the email address for your account.</p><form onSubmit={resend} className="space-y-4">{resendMessage && <p role="status" className="rounded-lg bg-teal-50 px-4 py-3 text-sm text-teal-900">{resendMessage}</p>}{resendError && <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800">{resendError}</p>}<Field label="Account email" name="email" type="email" value={resendEmail} onChange={(event) => setResendEmail(event.target.value)} autoComplete="email" required /><button disabled={resending || cooldown > 0} className="w-full rounded-lg bg-[#2563eb] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-700">{resending ? 'Sending…' : cooldown ? `Try again in ${cooldown}s` : 'Send a new verification link'}</button></form></> : null}</div>
  </AuthShell>;
}
