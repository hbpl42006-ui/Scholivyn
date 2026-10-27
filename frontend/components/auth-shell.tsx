import Link from 'next/link';
import { BookOpenCheck } from 'lucide-react';

export function AuthShell({ title, description, children, footer }: { title: string; description: React.ReactNode; children: React.ReactNode; footer: React.ReactNode }) {
  return <main className="grid min-h-screen bg-white lg:grid-cols-[1fr_1.05fr]">
    <aside className="hidden flex-col justify-between bg-[#102a43] p-10 text-white lg:flex xl:p-14">
      <Link href="/" className="flex items-center gap-3 text-lg font-semibold"><span className="grid h-10 w-10 place-items-center rounded-xl bg-white/10"><BookOpenCheck size={20} /></span>Scholivyn</Link>
      <div className="max-w-lg"><p className="text-sm font-semibold uppercase tracking-[.18em] text-teal-300">Research Smarter. Publish Better.</p><p className="serif mt-5 text-4xl leading-tight">A thoughtful workspace for your most important work.</p><p className="mt-5 leading-7 text-slate-300">Keep your research organized and move from draft to submission with confidence.</p></div>
      <p className="text-sm text-slate-400">© 2026 Scholivyn</p>
    </aside>
    <section className="flex min-h-screen flex-col px-5 py-6 sm:px-10 lg:px-16 xl:px-24">
      <Link href="/" className="flex items-center gap-3 font-semibold text-[#102a43] lg:hidden"><span className="grid h-9 w-9 place-items-center rounded-xl bg-[#102a43] text-white"><BookOpenCheck size={18} /></span>Scholivyn</Link>
      <div className="mx-auto my-auto w-full max-w-md py-12"><h1 className="text-3xl font-semibold tracking-tight text-[#102a43]">{title}</h1><p className="mt-2 text-sm leading-6 text-slate-600">{description}</p><div className="mt-8">{children}</div><div className="mt-6 text-sm text-slate-600">{footer}</div></div>
      <p className="text-center text-xs text-slate-400">Your research remains yours.</p>
    </section>
  </main>;
}

export function Field({ label, error, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  return <label className="block text-sm font-medium text-slate-700">{label}<input {...props} className={`mt-2 w-full rounded-lg border bg-white px-3.5 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-100 ${error ? 'border-red-400' : 'border-slate-300'}`} />{error && <span className="mt-1 block text-xs font-normal text-red-600">{error}</span>}</label>;
}

export function SubmitButton({ children, busy }: { children: React.ReactNode; busy: boolean }) {
  return <button disabled={busy} className="flex w-full items-center justify-center rounded-lg bg-[#2563eb] px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 disabled:cursor-wait disabled:bg-blue-700 disabled:text-white">{busy ? 'Please wait…' : children}</button>;
}
