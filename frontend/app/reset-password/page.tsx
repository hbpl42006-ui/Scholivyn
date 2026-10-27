'use client';
import { Suspense } from 'react';
import { ResetPasswordForm } from '@/components/auth-forms';
export default function ResetPasswordPage() { return <Suspense fallback={<div className="p-10 text-center text-slate-500">Loading password reset…</div>}><ResetPasswordForm /></Suspense>; }
