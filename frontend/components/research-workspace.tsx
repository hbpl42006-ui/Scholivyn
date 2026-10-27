'use client';

import Link from 'next/link';
import { BookOpen, FileText, LayoutDashboard, LogOut, ScanSearch, Sparkles, Quote, BookOpenCheck, CreditCard } from 'lucide-react';
import { useAuth } from '@/components/auth-provider';

const nav = [['Overview', '/dashboard', LayoutDashboard], ['Projects', '/dashboard/projects', BookOpen], ['Analyses', '/dashboard/analyses', Sparkles], ['Similarity', '/dashboard/similarity', ScanSearch], ['Citations', '/dashboard/citations', Quote], ['Journals', '/dashboard/journals', BookOpenCheck], ['Readiness', '/dashboard/publication-readiness', FileText], ['Billing', '/dashboard/billing', CreditCard]] as const;

export function ResearchWorkspace({ title, children }: { title: string; children: React.ReactNode }) {
  const { user, logout } = useAuth();
  return <div className="min-h-screen bg-[#f8fafc] md:flex">
    <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white p-5 md:block">
      <Link href="/dashboard" className="flex items-center gap-3 px-2 py-3 font-semibold text-[#102a43]"><span className="grid h-8 w-8 place-items-center rounded-lg bg-[#102a43] text-white"><BookOpen size={16} /></span>Scholivyn</Link>
      <p className="mb-4 mt-10 px-3 text-xs font-semibold uppercase tracking-widest text-slate-400">Workspace</p>
      <nav aria-label="Workspace navigation" className="space-y-1">{nav.map(([label, href, Icon]) => <Link key={href} href={href} className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-50"><Icon size={17} />{label}</Link>)}</nav>
      <div className="mt-9 border-t border-slate-100 pt-5"><p className="truncate px-3 text-xs text-slate-500">{user?.email}</p><button onClick={logout} className="mt-3 flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-50"><LogOut size={17} />Sign out</button></div>
    </aside>
    <main className="min-w-0 flex-1"><header className="border-b border-slate-200 bg-white px-5 py-5 sm:px-8"><div className="mx-auto max-w-6xl"><p className="text-sm text-slate-500">Research workspace</p><h1 className="mt-1 text-2xl font-semibold text-[#102a43]">{title}</h1><nav aria-label="Mobile workspace navigation" className="mt-3 flex gap-2 overflow-x-auto pb-1 md:hidden">{nav.map(([label, href]) => <Link key={href} href={href} className="shrink-0 rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">{label}</Link>)}</nav></div></header><div className="mx-auto max-w-6xl p-5 sm:p-8">{children}</div></main>
  </div>;
}

export function StatusBadge({ status }: { status: string }) {
  const classes = status === 'completed' ? 'bg-emerald-50 text-emerald-700' : status === 'failed' ? 'bg-rose-50 text-rose-700' : status === 'processing' ? 'bg-blue-50 text-blue-700' : status === 'waiting_for_quota' ? 'bg-violet-50 text-violet-800' : status === 'partially_completed' ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-700';
  const label = status.replaceAll('_', ' ');
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium capitalize ${classes}`}><FileText size={13} />{label}</span>;
}
