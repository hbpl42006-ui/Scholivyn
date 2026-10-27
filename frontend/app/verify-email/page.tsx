'use client';
import { Suspense } from 'react';
import { VerifyEmailStatus } from '@/components/verify-email-status';
export default function VerifyEmailPage() { return <Suspense fallback={<div className="p-10 text-center text-slate-500">Verifying…</div>}><VerifyEmailStatus /></Suspense>; }
