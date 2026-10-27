import Link from 'next/link';
import { ArrowRight, BookOpenCheck, CheckCircle2, Menu, ShieldCheck, Sparkles } from 'lucide-react';

const features = [
  ['Manuscript intelligence', 'Section-by-section feedback grounded in your own document.', '01'],
  ['Originality with context', 'Evidence-backed similarity review with transparent source coverage.', '02'],
  ['Publication readiness', 'References, structure and submission details in one focused workspace.', '03'],
];

export default function Home() {
  return (
    <main>
      <nav aria-label="Main navigation" className="mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8 lg:px-10">
        <Link href="/" className="flex items-center gap-3 font-semibold tracking-tight text-[#102a43]">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-[#102a43] text-white"><BookOpenCheck size={19} /></span>
          Scholivyn
        </Link>
        <div className="hidden items-center gap-8 text-sm text-slate-600 md:flex">
          <a className="transition-colors hover:text-blue-700" href="#features">Capabilities</a>
          <a className="transition-colors hover:text-blue-700" href="#workflow">How it works</a>
          <a className="transition-colors hover:text-blue-700" href="#trust">Privacy</a>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="rounded-full bg-[#102a43] px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-800 sm:px-5">Open workspace</Link>
          <a aria-label="Jump to capabilities" className="grid h-10 w-10 place-items-center rounded-full border border-slate-200 text-slate-700 md:hidden" href="#features"><Menu size={19} /></a>
        </div>
      </nav>

      <section className="grid-bg relative overflow-hidden border-y border-slate-200">
        <div className="mx-auto max-w-7xl px-5 pb-16 pt-16 sm:px-8 sm:pb-20 sm:pt-20 lg:px-10 lg:pb-28 lg:pt-28">
          <div className="max-w-4xl">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-white/90 px-3 py-1.5 text-xs font-semibold text-blue-700"><Sparkles size={14} /> A calmer way to finish important research</div>
            <h1 className="serif max-w-4xl text-5xl leading-[1.04] tracking-tight text-[#102a43] sm:text-6xl lg:text-7xl">Your Research.<br /><em className="text-[#2563eb]">Refined by Intelligence.</em></h1>
            <p className="mt-6 max-w-2xl text-base leading-7 text-slate-600 sm:mt-7 sm:text-lg sm:leading-8">Analyze manuscripts, improve academic writing, verify references and prepare research papers for publication with clarity and confidence.</p>
            <div className="mt-8 flex flex-col gap-3 xs:flex-row sm:mt-9 sm:flex-row">
              <Link href="/dashboard" className="flex items-center justify-center gap-2 rounded-full bg-[#2563eb] px-6 py-3.5 font-medium text-white shadow-md shadow-blue-200 transition-colors hover:bg-blue-700">Analyze your paper <ArrowRight size={17} /></Link>
              <a href="#features" className="rounded-full border border-slate-300 bg-white px-6 py-3.5 text-center font-medium text-[#102a43] transition-colors hover:border-slate-400 hover:bg-slate-50">Explore capabilities</a>
            </div>
          </div>
          <div className="mt-16 grid max-w-3xl grid-cols-1 gap-5 border-t border-slate-300 pt-6 text-sm sm:mt-20 sm:grid-cols-3 sm:gap-6">
            <div><p className="font-semibold text-[#102a43]">Built for researchers</p><p className="mt-1 text-slate-500">Students to principal investigators</p></div>
            <div><p className="font-semibold text-[#102a43]">Evidence first</p><p className="mt-1 text-slate-500">Clear provenance for every finding</p></div>
            <div><p className="font-semibold text-[#102a43]">Private by design</p><p className="mt-1 text-slate-500">Your unpublished work stays yours</p></div>
          </div>
        </div>
      </section>

      <section id="features" className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-10 lg:py-24">
        <div className="max-w-xl"><p className="text-sm font-semibold uppercase tracking-[.2em] text-teal-700">One research workspace</p><h2 className="serif mt-4 text-3xl text-[#102a43] sm:text-4xl">The details that make a paper stronger.</h2></div>
        <div className="mt-9 grid gap-4 sm:mt-12 md:grid-cols-3 md:gap-5">
          {features.map(([title, desc, num]) => <article key={title} className="rounded-2xl border border-slate-200 bg-white p-6 transition-shadow hover:shadow-lg hover:shadow-slate-200/60 sm:p-7"><span className="text-sm font-semibold text-blue-600">{num}</span><h3 className="mt-10 text-xl font-semibold text-[#102a43] sm:mt-16">{title}</h3><p className="mt-3 leading-7 text-slate-600">{desc}</p></article>)}
        </div>
      </section>

      <section id="workflow" className="border-y border-slate-200 bg-white">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-16 sm:px-8 sm:py-20 md:grid-cols-2 md:items-center lg:px-10">
          <div><p className="text-sm font-semibold uppercase tracking-[.2em] text-blue-700">A focused workflow</p><h2 className="serif mt-4 text-3xl text-[#102a43] sm:text-4xl">From first draft to a clearer next step.</h2></div>
          <ol className="grid gap-4 text-sm text-slate-600 sm:grid-cols-3"><li className="rounded-xl bg-slate-50 p-5"><span className="font-semibold text-blue-700">01</span><p className="mt-3 font-medium text-[#102a43]">Add your manuscript</p></li><li className="rounded-xl bg-slate-50 p-5"><span className="font-semibold text-blue-700">02</span><p className="mt-3 font-medium text-[#102a43]">Review evidence and suggestions</p></li><li className="rounded-xl bg-slate-50 p-5"><span className="font-semibold text-blue-700">03</span><p className="mt-3 font-medium text-[#102a43]">Choose what to improve</p></li></ol>
        </div>
      </section>

      <section id="trust" className="bg-[#102a43] text-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-8 px-5 py-16 sm:px-8 sm:py-20 md:flex-row md:items-center md:justify-between lg:px-10">
          <div><p className="text-sm font-semibold uppercase tracking-[.2em] text-teal-300">Research integrity</p><h2 className="serif mt-4 max-w-xl text-3xl sm:text-4xl">Useful intelligence, with clear limits.</h2></div>
          <div className="grid max-w-lg gap-4 text-sm leading-6 text-slate-300"><p className="flex gap-3"><ShieldCheck className="mt-0.5 shrink-0 text-teal-300" size={20} />No fabricated sources, scores or acceptance promises.</p><p className="flex gap-3"><CheckCircle2 className="mt-0.5 shrink-0 text-teal-300" size={20} />Findings distinguish verified evidence from model suggestions.</p></div>
        </div>
      </section>

      <footer className="mx-auto flex max-w-7xl flex-col gap-2 px-5 py-7 text-sm text-slate-500 sm:flex-row sm:justify-between sm:px-8 lg:px-10"><span>© 2026 Scholivyn</span><span>Research Smarter. Publish Better.</span></footer>
    </main>
  );
}
