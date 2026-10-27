'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Download, RotateCw, Trash2, X } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { deleteSimilarityJob, downloadSimilarityReport, filterSimilarityMatches, getSimilarityJob, similarityAction, similarityEvidenceHref, type SimilarityJob, type SimilarityMatch } from '@/lib/similarity';

function Passage({ before, matched, after }: { before: string; matched: string; after: string }) {
  return <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{before}<mark className="rounded bg-amber-200 px-0.5 text-amber-950">{matched}</mark>{after}</p>;
}

export default function SimilarityDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const router = useRouter();
  const [jobId, setJobId] = useState('');
  const [job, setJob] = useState<SimilarityJob | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [typeFilter, setTypeFilter] = useState('all');
  const [sectionFilter, setSectionFilter] = useState('all');
  const [confidence, setConfidence] = useState(0);

  useEffect(() => { void params.then(({ id }) => setJobId(id)); }, [params]);
  const load = useCallback(async () => {
    if (!jobId) return;
    try { setJob(await getSimilarityJob(jobId)); setError(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load this comparison.'); }
  }, [jobId]);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  useEffect(() => {
    if (!job || !['queued', 'processing'].includes(job.status)) return;
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [job, load]);

  const matches = useMemo(() => job?.comparisons.flatMap((comparison) => comparison.matches.map((match) => ({
    ...match,
    comparisonTitle: comparison.target_document_title,
    comparisonProject: comparison.target_project_title,
    sourceHref: similarityEvidenceHref(job.source_project_id, job.source_document_id, job.source_version_id, match.source_section_key, match.source_paragraph_index),
    targetHref: similarityEvidenceHref(comparison.target_project_id, comparison.target_document_id, comparison.target_version_id, match.target_section_key, match.target_paragraph_index),
  }))) ?? [], [job]);
  const sections = useMemo(() => [...new Set(matches.map((match) => match.source_section_title).filter(Boolean))].sort(), [matches]);
  const filtered = filterSimilarityMatches(matches, typeFilter, sectionFilter, confidence);
  async function action(kind: 'cancel' | 'retry') {
    if (!jobId) return;
    setBusy(true); setError('');
    try { setJob(await similarityAction(jobId, kind)); } catch (e) { setError(e instanceof Error ? e.message : `Could not ${kind} comparison.`); }
    finally { setBusy(false); }
  }
  async function removeReport() {
    if (!jobId || !window.confirm('Permanently delete this similarity report and its stored comparison findings? The source manuscripts and historical AI reviews will not be deleted.')) return;
    setBusy(true); setError('');
    try { await deleteSimilarityJob(jobId); router.push('/dashboard/similarity'); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not delete this report.'); }
    finally { setBusy(false); }
  }

  return <ResearchWorkspace title="Similarity report">
    <Link href="/dashboard/similarity" className="inline-flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700"><ArrowLeft size={16} />All comparisons</Link>
    {error && <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    {!job ? <p className="mt-6 text-sm text-slate-500">Loading comparison…</p> : <>
      <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-widest text-blue-700">{job.source_project_title}</p><h2 className="mt-1 text-xl font-semibold text-[#102a43]">{job.source_document_title}</h2><p className="mt-1 text-sm text-slate-600">Pinned source revision {job.source_revision}</p></div><div className="flex flex-wrap gap-2"><StatusBadge status={job.status} />{job.status === 'completed' && <button onClick={() => void downloadSimilarityReport(job.id).catch((e) => setError(e.message))} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"><Download size={15} />Download PDF</button>}{['queued','processing'].includes(job.status) && <button disabled={busy} onClick={() => void action('cancel')} className="inline-flex items-center gap-2 rounded-lg border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"><X size={15} />Cancel</button>}{job.status === 'failed' && <button disabled={busy} onClick={() => void action('retry')} className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"><RotateCw size={15} />Retry</button>}<button disabled={busy} onClick={() => void removeReport()} className="inline-flex items-center gap-2 rounded-lg border border-rose-200 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-50 disabled:opacity-50"><Trash2 size={15} />Delete report</button></div></div>
        {['queued','processing'].includes(job.status) && <div className="mt-5"><div className="flex justify-between text-sm text-slate-600"><span>{job.status === 'queued' ? 'Waiting for the similarity worker' : 'Comparing selected versions'}</span><span>{job.completed_targets}/{job.total_targets} sources · {job.progress}%</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-700 transition-all" style={{ width: `${job.progress}%` }} /></div></div>}
        {job.status === 'failed' && <p role="alert" className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{job.error_message || 'Comparison failed. Retry it after checking worker availability.'}</p>}
        {job.status === 'completed' && <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div className="rounded-xl bg-blue-50 p-4"><p className="text-xs text-blue-800">Matched source text</p><p className="mt-1 text-2xl font-semibold text-blue-950">{job.matched_percentage.toFixed(2)}%</p><p className="text-xs text-blue-800">{job.matched_source_words.toLocaleString()} / {job.source_word_count.toLocaleString()} non-reference words</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-600">Exact passages</p><p className="mt-1 text-2xl font-semibold text-[#102a43]">{job.exact_match_count}</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-600">Near-duplicate passages</p><p className="mt-1 text-2xl font-semibold text-[#102a43]">{job.near_match_count}</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-600">Comparison scope</p><p className="mt-1 text-2xl font-semibold text-[#102a43]">{job.total_targets}</p><p className="text-xs text-slate-600">selected versions only</p></div></div>}
      </section>
      {job.status === 'completed' && <>
        <section className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-950"><strong>Interpretation:</strong> Similarity is not proof of plagiarism, intent, or misconduct. Quoted and cited matches may be legitimate. This compares only the explicitly selected versions; it has no external scholarly/web coverage and is not equivalent to Turnitin.</section>
        <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-5"><div className="flex flex-wrap items-end justify-between gap-3"><div><h3 className="text-lg font-semibold text-[#102a43]">Matched passages</h3><p className="mt-1 text-sm text-slate-600">{filtered.length} of {matches.length} evidence-linked passage pairs</p></div><div className="flex flex-wrap gap-2"><label className="text-xs text-slate-600">Type<select aria-label="Filter by similarity type" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="ml-2 rounded-md border border-slate-300 bg-white p-2 text-sm"><option value="all">All types</option><option value="exact">Exact</option><option value="near_duplicate">Near duplicate</option></select></label><label className="text-xs text-slate-600">Section<select aria-label="Filter by section" value={sectionFilter} onChange={(e) => setSectionFilter(e.target.value)} className="ml-2 max-w-40 rounded-md border border-slate-300 bg-white p-2 text-sm"><option value="all">All sections</option>{sections.map((section) => <option key={section}>{section}</option>)}</select></label><label className="text-xs text-slate-600">Minimum similarity<select aria-label="Filter by confidence" value={confidence} onChange={(e) => setConfidence(Number(e.target.value))} className="ml-2 rounded-md border border-slate-300 bg-white p-2 text-sm"><option value={0}>All</option><option value={0.8}>80%+</option><option value={0.9}>90%+</option></select></label></div></div>
          {filtered.length === 0 ? <p className="mt-5 rounded-lg bg-slate-50 p-5 text-sm text-slate-600">No passages match these filters. No matching text does not establish originality outside the selected comparison scope.</p> : <div className="mt-4 space-y-4">{filtered.map((match) => <MatchCard key={`${match.comparisonTitle}-${match.id}`} match={match} />)}</div>}
        </section>
      </>}
    </>}
  </ResearchWorkspace>;
}

function MatchCard({ match }: { match: SimilarityMatch & { comparisonTitle: string; comparisonProject: string; sourceHref: string; targetHref: string } }) {
  return <article className="rounded-xl border border-slate-200 p-4"><header className="flex flex-wrap items-center justify-between gap-2"><div><span className="font-semibold text-[#102a43]">{match.match_type === 'exact' ? 'Exact passage' : 'Near duplicate'}</span><span className="ml-2 text-sm text-slate-500">{Math.round(match.similarity * 100)}% similarity</span></div><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${match.citation_label === 'quoted_or_cited' ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-900'}`}>{match.citation_label === 'quoted_or_cited' ? 'Citation/quotation signal' : 'No nearby citation signal'}</span></header><div className="mt-3 grid gap-3 lg:grid-cols-2"><div className="rounded-lg bg-slate-50 p-3"><p className="mb-2 text-xs font-semibold text-slate-700">{match.source_filename} · {match.source_section_title || 'Unclassified'} · paragraph {match.source_paragraph_index + 1}</p><Passage before={match.source_before} matched={match.source_match_text} after={match.source_after} /><Link className="mt-2 inline-block text-xs font-semibold text-blue-700 underline underline-offset-2 hover:text-blue-900" href={match.sourceHref}>Open source evidence at revision {match.source_revision}</Link></div><div className="rounded-lg bg-slate-50 p-3"><p className="mb-2 text-xs font-semibold text-slate-700">{match.comparisonTitle} · {match.target_section_title || 'Unclassified'} · paragraph {match.target_paragraph_index + 1}</p><Passage before={match.target_before} matched={match.target_match_text} after={match.target_after} /><Link className="mt-2 inline-block text-xs font-semibold text-blue-700 underline underline-offset-2 hover:text-blue-900" href={match.targetHref}>Open compared evidence at revision {match.target_revision}</Link></div></div><p className="mt-2 text-xs text-slate-500">Pinned source revision {match.source_revision} vs target revision {match.target_revision} · {match.source_word_count} matched source words · project {match.comparisonProject}</p></article>;
}
