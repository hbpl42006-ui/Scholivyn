'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { Download, ExternalLink, RotateCcw, XCircle } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { citationAction, citationSourceHref, downloadCitationReport, getCitationItems, getCitationJob,
  saveCitationDecision, type CitationItem, type CitationJob, type CitationPage } from '@/lib/citations';

type ItemKind = 'citations'|'references'|'findings';

export default function CitationAnalysisDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [job, setJob] = useState<CitationJob | null>(null);
  const [items, setItems] = useState<Record<ItemKind, CitationItem[]>>({ citations:[], references:[], findings:[] });
  const [counts, setCounts] = useState<Record<ItemKind, number>>({ citations:0, references:0, findings:0 });
  const [kind, setKind] = useState<ItemKind>('findings');
  const [filter, setFilter] = useState('');
  const [metadataConsent, setMetadataConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const loadJob = useCallback(async () => { setJob(await getCitationJob(id)); }, [id]);
  const loadItems = useCallback(async (type: ItemKind, offset = 0, append = false) => {
    const page: CitationPage<CitationItem> = await getCitationItems(id, type, offset);
    setCounts((current) => ({ ...current, [type]: page.count }));
    setItems((current) => ({ ...current, [type]: append ? [...current[type], ...page.results] : page.results }));
  }, [id]);

  useEffect(() => {
    let live = true;
    void Promise.all([getCitationJob(id), ...(['citations','references','findings'] as const).map((type) => getCitationItems(id, type))])
      .then(([loadedJob, citationPage, referencePage, findingPage]) => {
        if (!live) return;
        setJob(loadedJob);
        setItems({ citations:citationPage.results, references:referencePage.results, findings:findingPage.results });
        setCounts({ citations:citationPage.count, references:referencePage.count, findings:findingPage.count });
      }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Could not load this citation analysis.'))
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [id]);

  useEffect(() => {
    if (!job || !['queued','processing'].includes(job.status) && !['queued','processing'].includes(job.metadata_status)) return;
    const timer = window.setInterval(() => {
      void getCitationJob(id).then((fresh) => {
        const wasProcessing = job.status !== 'completed';
        setJob(fresh);
        if (wasProcessing && fresh.status === 'completed') {
          void Promise.all([loadItems('citations'), loadItems('references'), loadItems('findings')]);
        } else if (fresh.metadata_status === 'completed' || fresh.metadata_status === 'partial' || fresh.metadata_status === 'failed') {
          void loadItems('references');
        }
      }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Could not refresh analysis status.'));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [id, job, loadItems]);

  async function action(name: 'cancel'|'retry'|'verify-metadata') {
    setBusy(true); setError('');
    try {
      await citationAction(id, name, name === 'verify-metadata' && metadataConsent);
      await loadJob();
      if (name === 'verify-metadata') setMetadataConsent(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The action could not be completed.'); }
    finally { setBusy(false); }
  }

  async function decide(findingId: number, decision: 'accepted'|'rejected'|'needs_review') {
    setBusy(true); setError('');
    try { await saveCitationDecision(id, findingId, decision); await loadItems('findings'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save this review decision.'); }
    finally { setBusy(false); }
  }

  const visible = items[kind].filter((item) => `${item.raw_text ?? ''} ${item.title ?? ''} ${item.code ?? ''} ${item.explanation ?? ''}`.toLowerCase().includes(filter.toLowerCase()));
  const citationToSource = (item: CitationItem) => job ? citationSourceHref(job, item) : '#';

  return <ResearchWorkspace title="Citation analysis">
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><Link href="/dashboard/citations" className="text-sm font-medium text-blue-700 hover:underline">← All citation checks</Link>
      {job?.status === 'completed' && <button type="button" onClick={() => void downloadCitationReport(id).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Could not download report.'))} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"><Download size={16}/>Download PDF report</button>}
    </div>
    {error && <p role="alert" className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    {loading ? <p className="rounded-xl bg-white p-6 text-sm text-slate-500">Loading citation results…</p> : !job ? <p className="rounded-xl bg-white p-6 text-sm text-slate-600">Citation analysis not found.</p> : <>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-widest text-blue-700">{job.citation_style.toUpperCase()} · revision {job.revision_number}</p><h2 className="mt-2 text-xl font-semibold text-[#102a43]">{job.original_filename}</h2><p className="mt-1 text-sm text-slate-500">{job.project_title}</p></div><StatusBadge status={job.status}/></div>
        {job.status === 'processing' || job.status === 'queued' ? <div className="mt-5"><div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-700 transition-all" style={{ width:`${job.progress}%` }}/></div><p className="mt-2 text-xs text-slate-500">Processing asynchronously · {job.progress}%</p></div> : null}
        {job.status === 'failed' && <p role="status" className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{job.error_message || 'Analysis failed.'} {job.error_category && <span className="text-xs">({job.error_category})</span>}</p>}
        {job.status === 'cancelled' && <p role="status" className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">This analysis was cancelled. Completed results were retained.</p>}
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{[
          ['Citations',job.citation_count],['References',job.reference_count],['Matched',job.matched_count],['Unmatched',job.unmatched_count],['Ambiguous',job.ambiguous_count],
        ].map(([label,value]) => <div key={label} className="rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold text-[#102a43]">{value}</p></div>)}</div>
        <p className="mt-4 text-sm text-slate-600">Metadata verification: <strong className="capitalize">{job.metadata_status.replaceAll('_',' ')}</strong>. Provider records are candidates only; they do not establish authenticity or misconduct.</p>
        <div className="mt-4 flex flex-wrap gap-2">{['queued','processing'].includes(job.status) && <button disabled={busy} onClick={() => void action('cancel')} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"><XCircle size={15}/>Cancel</button>}{job.status === 'failed' && <button disabled={busy} onClick={() => void action('retry')} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"><RotateCcw size={15}/>Retry</button>}</div>
      </section>

      {job.status === 'completed' && (!job.metadata_consent || ['failed','partial','not_checked'].includes(job.metadata_status)) && <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4"><p className="font-semibold text-[#102a43]">Optional metadata verification</p><p className="mt-1 text-sm text-slate-600">Only reference DOI/title/author/year fields are sent to Crossref and OpenAlex. Manuscript body text is not sent. A previous lookup may be resumed; completed provider checks are retained.</p>{job.metadata_status === 'failed' && <p role="status" className="mt-2 text-sm text-amber-800">The previous lookup could not finish. Confirm again to retry the remaining checks.</p>}<label className="mt-3 flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" checked={metadataConsent} onChange={(event) => setMetadataConsent(event.target.checked)} className="mt-1 accent-blue-700"/>I consent to metadata-only external lookups.</label><button disabled={busy || !metadataConsent} onClick={() => void action('verify-metadata')} className="mt-3 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:bg-slate-300">Verify reference metadata</button></section>}

      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap gap-2">{(['findings','citations','references'] as const).map((value) => <button key={value} type="button" onClick={() => setKind(value)} aria-pressed={kind === value} className={`rounded-lg px-3 py-2 text-sm font-medium capitalize ${kind === value ? 'bg-blue-700 text-white' : 'border border-slate-200 text-slate-700 hover:bg-slate-50'}`}>{value} ({counts[value]})</button>)}</div><input aria-label="Filter citation results" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter results" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm sm:w-64"/></div>
        {visible.length === 0 ? <p className="mt-5 rounded-lg bg-slate-50 p-5 text-sm text-slate-500">{items[kind].length ? 'No results match this filter.' : 'No items were detected in this category.'}</p> : <div className="mt-4 space-y-3">{visible.map((item) => <article key={`${kind}-${item.id}`} className="rounded-xl border border-slate-200 p-4">
          {kind === 'findings' ? <><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-[#102a43]">{(item.code ?? '').replaceAll('_',' ')}</h3><span className="rounded-full bg-amber-50 px-2 py-1 text-xs text-amber-900">{item.severity?.replaceAll('_',' ')}</span></div><p className="mt-2 text-sm leading-6 text-slate-600">{item.explanation}</p>{item.excerpt && <blockquote className="mt-3 border-l-2 border-blue-300 pl-3 text-sm text-slate-700">{item.excerpt}</blockquote>}{item.source_section_key && <Link href={citationToSource(item)} className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline">Open source evidence <ExternalLink size={13}/></Link>}{!item.review_decision ? <div className="mt-3 flex gap-2"><button disabled={busy} onClick={() => void decide(item.id,'accepted')} className="rounded-md border border-emerald-300 px-3 py-1.5 text-xs font-semibold text-emerald-800 disabled:opacity-50">Reviewed</button><button disabled={busy} onClick={() => void decide(item.id,'needs_review')} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 disabled:opacity-50">Needs review</button><button disabled={busy} onClick={() => void decide(item.id,'rejected')} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-600 disabled:opacity-50">Dismiss</button></div> : <p className="mt-3 text-xs text-slate-500">Review decision: {item.review_decision.decision.replaceAll('_',' ')}{item.review_decision.note && ` · ${item.review_decision.note}`}</p>}</> : kind === 'citations' ? <><p className="font-medium text-[#102a43]">{item.raw_text}</p><p className="mt-1 text-xs text-slate-500">{item.style?.toUpperCase()} · {item.section_title} · paragraph {item.paragraph_index !== undefined ? item.paragraph_index + 1 : '—'} · {item.start_offset}–{item.end_offset}</p><p className="mt-2 text-sm text-slate-600">Match status: <strong className="capitalize">{item.match_status?.replaceAll('_',' ')}</strong></p><Link href={citationToSource(item)} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline">Open citation in manuscript <ExternalLink size={13}/></Link></> : <><p className="font-medium text-[#102a43]">{item.title || item.raw_text}</p><p className="mt-1 text-sm text-slate-600">{item.authors?.join('; ')}{item.year ? ` · ${item.year}` : ''}{item.doi ? ` · DOI ${item.doi}` : ''}</p><p className="mt-1 text-xs text-slate-500">Reference {item.reference_number ?? 'un-numbered'} · {item.confidence} parse · {item.match_status?.replaceAll('_',' ')}</p>{item.findings?.length ? <p className="mt-2 text-xs text-amber-800">Flags: {item.findings.join(', ').replaceAll('_',' ')}</p> : null}{item.metadata_checks?.map((check) => <div key={check.provider} className="mt-3 rounded-lg bg-slate-50 p-3 text-sm"><p className="font-medium capitalize text-[#102a43]">{check.provider}: {check.status.replaceAll('_',' ')}</p>{typeof check.metadata.explanation === 'string' && <p className="mt-1 text-slate-600">{check.metadata.explanation}</p>}{check.source_url && <a href={check.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs text-blue-700 underline">View provider record</a>}</div>)}<Link href={citationToSource(item)} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline">Open reference text <ExternalLink size={13}/></Link></>}
        </article>)}</div>}
        {items[kind].length < counts[kind] && <button onClick={() => void loadItems(kind, items[kind].length, true)} className="mt-4 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Load more {kind}</button>}
      </section>
      <p className="mt-5 text-xs leading-5 text-slate-500">Structural checks and registry metadata do not prove plagiarism, fabrication, misconduct, or source quality. APA/IEEE checks are limited structural heuristics, not comprehensive certification.</p>
    </>}
  </ResearchWorkspace>;
}
