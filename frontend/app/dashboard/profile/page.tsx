'use client';
import { useAuth } from '@/components/auth-provider';
export default function ProfilePage() {
  const { user } = useAuth();
  return <section className="rounded-2xl border border-slate-200 bg-white p-6 sm:p-8"><p className="text-sm font-semibold uppercase tracking-widest text-blue-700">Your account</p><h2 className="mt-2 text-xl font-semibold text-[#102a43]">Profile</h2><dl className="mt-7 grid gap-5 sm:grid-cols-2">{[['Name', user?.full_name || user?.username], ['Email', user?.email], ['Username', user?.username], ['Role', user?.role]].map(([label, value]) => <div key={label}><dt className="text-sm text-slate-500">{label}</dt><dd className="mt-1 font-medium capitalize text-slate-900">{value || '—'}</dd></div>)}</dl></section>;
}
