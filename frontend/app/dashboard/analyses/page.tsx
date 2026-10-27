'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Sparkles } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { researchRequest, type Project, type ResearchDocument } from '@/lib/research';
import type { AnalysisJob } from '@/lib/intelligence';
import { documentAnalysisHref, isExtractionComplete } from '@/lib/analysis-navigation';

export default function AnalysesPage() {
  const [jobs, setJobs] = useState<AnalysisJob[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [documents, setDocuments] = useState<ResearchDocument[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [loadedProjectId, setLoadedProjectId] = useState('');
  const [selectionError, setSelectionError] = useState('');
  const load = useCallback(async () => {
    try { setJobs(await researchRequest<AnalysisJob[]>('analyses/')); setError(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load your analyses.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);
  useEffect(() => {
    let live = true;
    void researchRequest<Project[]>('projects/').then((rows) => {
      if (!live) return;
      setProjects(rows);
      setSelectedProjectId((current) => current && rows.some((project) => project.id === current) ? current : rows[0]?.id ?? '');
    }).catch((e) => {
      if (live) setSelectionError(e instanceof Error ? e.message : 'Could not load your projects.');
    }).finally(() => { if (live) setProjectsLoading(false); });
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!selectedProjectId) return;
    let live = true;
    void researchRequest<ResearchDocument[]>(`projects/${selectedProjectId}/documents/`).then((rows) => {
      if (live) { setDocuments(rows); setSelectionError(''); }
    }).catch((e) => {
      if (live) setSelectionError(e instanceof Error ? e.message : 'Could not load manuscripts for this project.');
    }).finally(() => { if (live) setLoadedProjectId(selectedProjectId); });
    return () => { live = false; };
  }, [selectedProjectId]);
  const extractionPending = documents.some((document) => ['pending', 'processing'].includes(document.current_version?.processing_status ?? ''));
  useEffect(() => {
    if (!selectedProjectId || !extractionPending) return;
    const timer = window.setInterval(() => {
      void researchRequest<ResearchDocument[]>(`projects/${selectedProjectId}/documents/`)
        .then(setDocuments)
        .catch((e) => setSelectionError(e instanceof Error ? e.message : 'Could not refresh manuscript processing status.'));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [selectedProjectId, extractionPending]);
  const active = jobs.some((job) => ['queued', 'processing', 'waiting_for_quota'].includes(job.status));
  useEffect(() => { if (!active) return; const timer = window.setInterval(() => void load(), 45000); return () => window.clearInterval(timer); }, [active, load]);

  return <ResearchWorkspace title="Research analyses">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm font-semibold uppercase tracking-widest text-blue-700">Research intelligence</p><h2 className="mt-2 text-xl font-semibold text-[#102a43]">Academic review history</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">Review extracted manuscripts with evidence-linked, section-level feedback. Analysis is only sent to the configured AI provider after you consent.</p></div><a href="#manuscript-selection" className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800">Choose a manuscript <ArrowRight size={16} /></a></div>
    {error && <p role="alert" className="mt-5 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{error}</p>}
    <section id="manuscript-selection" className="mt-7 scroll-mt-6 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6" aria-labelledby="manuscript-selection-title">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-widest text-blue-700">Start a review</p><h3 id="manuscript-selection-title" className="mt-1 text-lg font-semibold text-[#102a43]">Select a manuscript</h3><p className="mt-1 text-sm text-slate-600">Choose a project document. Only completed extractions can be analyzed.</p></div>{projects.length > 0 && <label className="w-full text-sm font-medium text-slate-700 sm:max-w-sm">Project<select aria-label="Select research project" value={selectedProjectId} onChange={(event) => { setDocuments([]); setLoadedProjectId(''); setSelectionError(''); setSelectedProjectId(event.target.value); }} className="mt-1.5 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-800 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-100">{projects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}</select></label>}</div>
      {selectionError && <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{selectionError}</p>}
      {projectsLoading || Boolean(selectedProjectId && loadedProjectId !== selectedProjectId) ? <p className="mt-5 text-sm text-slate-500">Loading your manuscripts...</p> : projects.length === 0 ? <div className="mt-5 rounded-xl border border-dashed border-slate-300 p-6 text-center"><p className="text-sm text-slate-600">Create a research project and upload a manuscript before starting an analysis.</p><Link href="/dashboard/projects/new" className="mt-3 inline-flex rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-[#102a43] hover:bg-slate-50">Create a project</Link></div> : documents.length === 0 ? <p className="mt-5 rounded-xl bg-slate-50 p-5 text-sm text-slate-600">This project has no uploaded manuscripts yet. Upload one from the project page.</p> : <div className="mt-5 divide-y divide-slate-100 rounded-xl border border-slate-200">{documents.map((document) => {
        const status = document.current_version?.processing_status ?? 'pending';
        const ready = isExtractionComplete(status);
        return <div key={document.id} className="flex flex-wrap items-center justify-between gap-3 p-4"><div className="min-w-0"><Link href={`/dashboard/projects/${selectedProjectId}/documents/${document.id}`} className="truncate font-medium text-[#102a43] hover:text-blue-700">{document.original_filename}</Link><p className="mt-1 text-xs text-slate-500">{projects.find((project) => project.id === selectedProjectId)?.title} · {document.current_version ? `Revision ${document.current_version.revision_number}` : 'No uploaded version'}</p><div className="mt-2"><StatusBadge status={status} /></div></div>{ready ? <Link href={documentAnalysisHref(selectedProjectId, document.id)} className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2"><Sparkles size={15} />Analyze paper with AI</Link> : status === 'failed' ? <Link href={`/dashboard/projects/${selectedProjectId}/documents/${document.id}`} className="rounded-lg border border-rose-200 px-3 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50">Review extraction issue</Link> : <span className="text-sm text-slate-500">Available after extraction completes</span>}</div>;
      })}</div>}
    </section>
    {loading ? <p className="mt-8 text-sm text-slate-500">Loading analyses…</p> : jobs.length === 0 ? <section className="mt-7 rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center"><span className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-blue-50 text-blue-700"><Sparkles /></span><h3 className="mt-4 font-semibold text-[#102a43]">No analyses yet</h3><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">Open an extracted manuscript and choose “Analyze paper with AI” to start a review.</p><Link href="/dashboard/projects" className="mt-5 inline-flex rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-[#102a43] hover:bg-slate-50">Browse projects</Link></section> : <div className="mt-7 space-y-3">{jobs.map((job) => <Link key={job.id} href={`/dashboard/analyses/${job.id}`} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-5 transition hover:border-blue-200 hover:shadow-sm"><div className="min-w-0"><p className="truncate font-semibold text-[#102a43]">{job.document_title}</p><p className="mt-1 text-xs text-slate-500">{job.project_title} · {new Date(job.created_at).toLocaleString()} · {job.provider} / {job.model_identifier || 'model not set'}</p><p className="mt-2 text-xs text-slate-500">{job.chunk_counts.completed}/{job.chunk_counts.total} chunks complete · {job.chunk_counts.failed} failed · {job.chunk_counts.pending} pending · {job.input_tokens.toLocaleString()} input / {job.output_tokens.toLocaleString()} output tokens</p></div><div className="flex items-center gap-3"><StatusBadge status={job.status} />{['queued', 'processing', 'waiting_for_quota'].includes(job.status) && <span className="text-xs text-slate-500">{job.progress}%</span>}<ArrowRight size={16} className="text-slate-400" /></div></Link>)}</div>}
  </ResearchWorkspace>;
}
