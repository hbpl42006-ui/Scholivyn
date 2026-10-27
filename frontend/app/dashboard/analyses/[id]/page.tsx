'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Download, ExternalLink, RotateCw } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { researchRequest, sourceParagraphElementId, type ExtractedSection, type Version } from '@/lib/research';
import { downloadAnalysisReport, formatReasoningTokenUsage, getAnalysis, getAnalysisIssues, getAnalysisSections, resumeAnalysis, updateAnalysisIssue, type AnalysisIssue, type AnalysisJob, type AnalysisSection } from '@/lib/intelligence';
import { analysisFailureGuidance } from '@/lib/analysis-navigation';

const sourceId = sourceParagraphElementId;

export default function AnalysisDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<AnalysisJob | null>(null);
  const [sections, setSections] = useState<AnalysisSection[]>([]);
  const [sourceSections, setSourceSections] = useState<ExtractedSection[]>([]);
  const [sourceVersionMissing, setSourceVersionMissing] = useState(false);
  const [issues, setIssues] = useState<AnalysisIssue[]>([]);
  const [issueCount, setIssueCount] = useState(0);
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState('all');
  const [sectionFilter, setSectionFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [activeSource, setActiveSource] = useState('');

  const load = useCallback(async () => {
    try {
      const current = await getAnalysis(id);
      const [sectionRows, pageData] = await Promise.all([getAnalysisSections(id), getAnalysisIssues(id, 1)]);
      setJob(current); setSections(sectionRows); setIssues(pageData.results); setIssueCount(pageData.count); setPage(1); setError('');
      if (current.document) {
        const versions = await researchRequest<Version[]>(`documents/${current.document}/versions/`);
        const analyzedVersion = versions.find((version) => version.id === current.document_version);
        setSourceVersionMissing(!analyzedVersion);
        setSourceSections(analyzedVersion?.extraction_metadata.sections ?? []);
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not load this analysis.'); }
  }, [id]);

  useEffect(() => { let live = true; const timer = window.setTimeout(() => { if (live) void load(); }, 0); return () => { live = false; window.clearTimeout(timer); }; }, [load]);
  const analysisStatus = job?.status;
  useEffect(() => {
    if (!analysisStatus || !['queued', 'processing', 'waiting_for_quota'].includes(analysisStatus)) return;
    const timer = window.setInterval(() => { void load(); }, analysisStatus === 'waiting_for_quota' ? 15000 : 3000);
    return () => window.clearInterval(timer);
  }, [analysisStatus, load]);

  const shownIssues = useMemo(() => issues.filter((issue) =>
    (severity === 'all' || issue.severity === severity) &&
    (sectionFilter === 'all' || issue.section_category === sectionFilter) &&
    (!search || `${issue.title} ${issue.explanation} ${issue.evidence_snippet}`.toLowerCase().includes(search.toLowerCase()))),
  [issues, severity, sectionFilter, search]);

  async function decide(issueId: string, value: { resolution_status?: string; suggestion_status?: string }) {
    setBusy(true); setError('');
    try {
      const updated = await updateAnalysisIssue(issueId, value);
      setIssues((rows) => rows.map((item) => item.id === issueId ? updated : item));
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save this review decision.'); }
    finally { setBusy(false); }
  }

  async function loadMore() {
    setBusy(true);
    try { const next = await getAnalysisIssues(id, page + 1); setIssues((rows) => [...rows, ...next.results]); setPage(page + 1); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load more findings.'); }
    finally { setBusy(false); }
  }

  async function downloadReport() {
    setBusy(true); setError('');
    try {
      const blob = await downloadAnalysisReport(id); const url = URL.createObjectURL(blob);
      const link = window.document.createElement('a'); link.href = url; link.download = `scholivyn-analysis-${id}.pdf`;
      link.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not download the report.'); }
    finally { setBusy(false); }
  }

  async function resumeSavedAnalysis() {
    setBusy(true); setError('');
    try { await resumeAnalysis(id); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not resume saved analysis work.'); }
    finally { setBusy(false); }
  }

  function jumpToEvidence(issue: AnalysisIssue) {
    const legacySectionIndex = Number.parseInt(issue.section_key.split('-', 1)[0], 10);
    const section = sourceSections.find((item) => item.section_key && item.section_key === issue.section_key)
      ?? (Number.isInteger(legacySectionIndex) && sourceSections[legacySectionIndex]?.title.toLowerCase() === issue.section_title.toLowerCase() ? sourceSections[legacySectionIndex] : undefined)
      ?? sourceSections.find((item) => item.title.toLowerCase() === issue.section_title.toLowerCase());
    if (!section || issue.source_paragraph_index === null) return;
    const elementId = sourceId(section, issue.source_paragraph_index);
    setActiveSource(elementId); window.document.getElementById(elementId)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  return <ResearchWorkspace title="Academic review">
    <div className="flex flex-wrap items-center justify-between gap-3"><Link href="/dashboard/analyses" className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-blue-700"><ArrowLeft size={16} />All analyses</Link>{job && <button type="button" disabled={busy || !['completed', 'partially_completed'].includes(job.status)} onClick={downloadReport} className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-600"><Download size={16} />Download report</button>}</div>
    {error && <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    {!job ? <p className="mt-7 text-sm text-slate-500">Loading analysis…</p> : <>
      <section className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-5"><div className="min-w-0"><h2 className="truncate text-lg font-semibold text-[#102a43]">{job.document_title}</h2><p className="mt-1 text-sm text-slate-500">{job.project_title} · {job.provider} / {job.model_identifier || 'model not configured'} · {job.reviewer_profile.replaceAll('_', ' ')} · {job.input_tokens.toLocaleString()} input / {job.output_tokens.toLocaleString()} output tokens</p>{job.reasoning_tokens !== null && <p className="mt-1 text-xs text-slate-500">{formatReasoningTokenUsage(job.reasoning_tokens)}</p>}<p className="mt-1 text-xs text-slate-500">Created {new Date(job.created_at).toLocaleString()} · Prompt {job.prompt_version}</p><p className="mt-2 text-xs text-slate-600">{job.chunk_counts.completed} completed · {job.chunk_counts.failed} failed · {job.chunk_counts.pending} pending chunks</p></div><div className="flex items-center gap-3"><StatusBadge status={job.status} /><span className="text-sm text-slate-600">{job.progress}% successful work</span></div></section>
      {['queued', 'processing', 'waiting_for_quota'].includes(job.status) && <section className={`mt-4 rounded-xl border p-4 ${job.status === 'waiting_for_quota' ? 'border-violet-100 bg-violet-50' : 'border-blue-100 bg-blue-50'}`}><div className="flex items-center gap-2 text-sm font-medium text-blue-900"><RotateCw size={16} className={job.status === 'waiting_for_quota' ? '' : 'animate-spin'} />{job.status === 'waiting_for_quota' ? 'Waiting for provider quota; saved chunks will resume automatically' : 'Analysis is processing asynchronously'}</div><div className="mt-3 h-2 overflow-hidden rounded-full bg-blue-100"><div className="h-full rounded-full bg-blue-700 transition-all" style={{ width: `${job.progress}%` }} /></div><p className="mt-2 text-xs text-blue-800">{job.chunk_counts.completed} of {job.chunk_counts.total} chunks complete; {job.chunk_counts.pending} pending. {job.next_attempt_at ? `Next resume after ${new Date(job.next_attempt_at).toLocaleTimeString()}.` : 'This view refreshes automatically.'} No document text is changed.</p></section>}
      {job.error_message && <div role="status" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><p>{job.error_message}</p>{analysisFailureGuidance(job.error_category) && <p className="mt-1">{analysisFailureGuidance(job.error_category)}</p>}{['failed', 'partially_completed'].includes(job.status) && <div className="mt-3 flex flex-wrap gap-2">{(job.chunk_counts.pending > 0 || ['provider_rate_limit', 'provider_unavailable', 'provider_quota_unavailable'].includes(job.error_category)) && <button type="button" disabled={busy} onClick={() => void resumeSavedAnalysis()} className="rounded-lg bg-blue-700 px-3 py-2 font-semibold text-white hover:bg-blue-800 disabled:bg-slate-300">Resume saved analysis</button>}<Link href={`/dashboard/projects/${job.project}/documents/${job.document}/analysis`} className="inline-flex rounded-lg border border-amber-300 px-3 py-2 font-semibold hover:bg-amber-100">Start a new analysis</Link></div>}</div>}
      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-5"><h3 className="font-semibold text-[#102a43]">Original manuscript</h3><p className="mt-1 text-xs text-slate-500">Read-only source from the exact extracted version reviewed</p>{sourceVersionMissing && <p role="status" className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-900">The analyzed document version is unavailable; evidence is not being mapped to a newer revision.</p>}<nav aria-label="Source sections" className="mt-3 flex flex-wrap gap-2">{sourceSections.map((section, index) => <button key={section.section_key ?? `${section.title}-${index}`} onClick={() => { const target = sourceId(section, 0); window.document.getElementById(target)?.scrollIntoView({ behavior: 'smooth' }); }} style={{ marginInlineStart: `${Math.max(0, (section.level ?? 1) - 1) * 12}px` }} className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">{section.title}</button>)}</nav><div className="mt-4 max-h-[75vh] space-y-5 overflow-auto pr-2">{sourceSections.map((section, sectionIndex) => <div key={section.section_key ?? `${section.title}-${sectionIndex}`}><h4 className="sticky top-0 mb-2 bg-white py-1 text-sm font-semibold text-[#146c80]" style={{ marginInlineStart: `${Math.max(0, (section.level ?? 1) - 1) * 12}px` }}>{section.title}</h4>{section.paragraphs.map((paragraph, index) => { const targetId = sourceId(section, index); return <p id={targetId} key={targetId} className={`mb-3 scroll-mt-3 whitespace-pre-wrap rounded-md text-sm leading-6 text-slate-700 ${activeSource === targetId ? 'bg-amber-50 ring-2 ring-amber-200' : ''}`}>{paragraph}</p>; })}</div>)}</div></section>
        <section className="min-w-0"><div className="rounded-xl border border-slate-200 bg-white p-4"><h3 className="font-semibold text-[#102a43]">Section review</h3><div className="mt-3 space-y-3">{sections.map((section) => <details key={section.id} className="rounded-lg border border-slate-200 p-3"><summary className="cursor-pointer text-sm font-semibold text-slate-800">{section.section_title} <span className="ml-2 text-xs font-normal text-slate-500">{section.processing_status}</span></summary><p className="mt-2 text-sm leading-6 text-slate-600">{section.review_summary}</p>{section.strengths.length > 0 && <p className="mt-2 text-xs text-emerald-800">Strengths: {section.strengths.join(' · ')}</p>}{section.weaknesses.length > 0 && <p className="mt-2 text-xs text-amber-800">Areas to strengthen: {section.weaknesses.join(' · ')}</p>}</details>)}</div></div>
          <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold text-[#102a43]">Findings</h3><p className="mt-1 text-xs text-slate-500">{issueCount} evidence-checked issue{issueCount === 1 ? '' : 's'} · AI suggestions are not applied to the manuscript.</p></div></div><div className="mt-3 grid gap-2 sm:grid-cols-3"><select aria-label="Filter by severity" value={severity} onChange={(e) => setSeverity(e.target.value)} className="rounded-md border border-slate-300 px-2 py-2 text-xs text-slate-700"><option value="all">All severities</option>{['critical', 'high', 'medium', 'low', 'informational'].map((value) => <option key={value}>{value}</option>)}</select><select aria-label="Filter by section" value={sectionFilter} onChange={(e) => setSectionFilter(e.target.value)} className="rounded-md border border-slate-300 px-2 py-2 text-xs text-slate-700"><option value="all">All sections</option>{sections.map((section) => <option key={section.id} value={section.section_category}>{section.section_title}</option>)}</select><input aria-label="Search findings" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search findings" className="rounded-md border border-slate-300 px-2 py-2 text-xs text-slate-700" /></div>
            <div className="mt-3 space-y-3">{shownIssues.map((issue) => <article key={issue.id} className="rounded-lg border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><button type="button" onClick={() => jumpToEvidence(issue)} className="text-left font-semibold text-[#102a43] hover:text-blue-700">{issue.title}<span className="ml-2 text-xs font-medium uppercase text-slate-500">{issue.severity}</span></button><span className="rounded-full bg-slate-100 px-2 py-1 text-xs capitalize text-slate-600">{issue.resolution_status}</span></div><p className="mt-1 text-xs text-slate-500">{issue.section_title} · {issue.category.replaceAll('_', ' ')}</p><blockquote className="mt-3 border-l-2 border-blue-300 pl-3 text-sm italic leading-6 text-slate-700">{issue.evidence_snippet}</blockquote><p className="mt-3 text-sm leading-6 text-slate-600">{issue.explanation}</p><p className="mt-2 text-sm leading-6 text-slate-700"><b>Recommendation:</b> {issue.suggested_improvement}</p>{issue.suggestion && <div className="mt-3 rounded-lg bg-teal-50 p-3"><p className="text-xs font-semibold text-teal-900">Suggested wording · {issue.suggestion.status}</p><p className="mt-2 text-sm text-slate-800"><span className="text-slate-500">Original:</span> {issue.suggestion.original_text}</p><p className="mt-1 text-sm text-slate-800"><span className="text-slate-500">Suggestion:</span> {issue.suggestion.suggested_text}</p><p className="mt-2 text-xs text-slate-600">Accepting or rejecting records your decision only; it does not edit the manuscript.</p><div className="mt-3 flex gap-2"><button disabled={busy} onClick={() => void decide(issue.id, { suggestion_status: 'accepted' })} className="rounded-md bg-teal-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-teal-800 disabled:bg-slate-300">Accept suggestion</button><button disabled={busy} onClick={() => void decide(issue.id, { suggestion_status: 'rejected' })} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-white disabled:text-slate-400">Reject</button></div></div>}{!issue.suggestion && issue.resolution_status === 'open' && <button disabled={busy} onClick={() => void decide(issue.id, { resolution_status: 'resolved' })} className="mt-3 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:text-slate-400">Mark resolved</button>}<button onClick={() => jumpToEvidence(issue)} className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:text-blue-900"><ExternalLink size={13} />Locate evidence</button></article>)}{shownIssues.length === 0 && <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No findings match these filters.</p>}</div>{issues.length < issueCount && <button disabled={busy} onClick={() => void loadMore()} className="mt-3 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:text-slate-400">Load more findings</button>}</div>
        </section>
      </div>
    </>}
  </ResearchWorkspace>;
}
