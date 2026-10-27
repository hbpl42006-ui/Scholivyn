'use client';
import { Suspense } from 'react';
import { LoginForm } from '@/components/auth-forms';
export default function LoginPage() { return <Suspense fallback={<div className="p-10 text-center text-slate-500">Loading sign in…</div>}><LoginForm /></Suspense>; }
