'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, ScanSearch } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { researchRequest, type Project, type ResearchDocument } from '@/lib/research';
import { createSimilarityJob, listSimilarityJobs, type SimilarityJob } from '@/lib/similarity';

type Choice = { versionId: string; documentId: string; projectId: string; projectTitle: string; filename: string; revision: number };

export default function SimilarityPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<SimilarityJob[]>([]);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [sourceId, setSourceId] = useState('');
  const [targets, setTargets] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    void Promise.all([listSimilarityJobs(), researchRequest<Project[]>('projects/')]).then(async ([history, projects]) => {
      const documents = await Promise.all(projects.map((project) => researchRequest<ResearchDocument[]>(`projects/${project.id}/documents/`).then((rows) => rows.map((document) => ({ project, document })))));
      if (!live) return;
      setJobs(history);
      const available = documents.flatMap((group) => group.flatMap(({ project, document }) => (document.versions.length ? document.versions : document.current_version ? [document.current_version] : []).flatMap((version) => version.processing_status === 'completed' ? [{ versionId: version.id, documentId: document.id, projectId: project.id, projectTitle: project.title, filename: version.original_filename, revision: version.revision_number }] : [])));
      setChoices(available);
      setSourceId((current) => current && available.some((choice) => choice.versionId === current) ? current : available[0]?.versionId ?? '');
    }).catch((e: unknown) => setError(e instanceof Error ? e.message : 'Could not load your manuscripts.')).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  const source = choices.find((item) => item.versionId === sourceId);
  const eligibleTargets = useMemo(() => choices.filter((item) => item.versionId !== sourceId), [choices, sourceId]);
  const toggleTarget = (id: string) => setTargets((current) => current.includes(id) ? current.filter((value) => value !== id) : current.length >= 10 ? current : [...current, id]);
  async function submit() {
    if (!sourceId || targets.length === 0) return;
    setSubmitting(true); setError('');
    try {
      const job = await createSimilarityJob(sourceId, targets, crypto.randomUUID());
      router.push(`/dashboard/similarity/${job.id}`);
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not start the comparison.'); setSubmitting(false); }
  }

  return <ResearchWorkspace title="Document similarity">
    <div className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
      <p className="text-xs font-semibold uppercase tracking-widest text-blue-700">Selected-source comparison</p>
      <h2 className="mt-2 text-xl font-semibold text-[#102a43]">Compare manuscript versions</h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Compare only versions you choose and are authorized to access. Scholivyn does not search public websites or external scholarly databases here.</p>
      {error && <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
      {loading ? <p className="mt-5 text-sm text-slate-500">Loading completed manuscript versions…</p> : choices.length < 2 ? <div className="mt-5 rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-600">At least two completed, accessible manuscript versions are needed for comparison. Upload a new version or add another manuscript.</div> : <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <label className="text-sm font-medium text-slate-700">Source version<select aria-label="Source version" value={sourceId} onChange={(event) => { setSourceId(event.target.value); setTargets([]); }} className="mt-2 w-full rounded-lg border border-slate-300 bg-white p-3 text-slate-800">{choices.map((choice) => <option key={choice.versionId} value={choice.versionId}>{choice.filename} · {choice.projectTitle} · v{choice.revision}</option>)}</select></label>
        <fieldset className="rounded-xl border border-slate-200 p-4"><legend className="px-1 text-sm font-medium text-slate-700">Compare against (up to 10)</legend><div className="max-h-64 space-y-2 overflow-y-auto">{eligibleTargets.map((choice) => <label key={choice.versionId} className="flex cursor-pointer items-start gap-3 rounded-lg p-2 text-sm hover:bg-slate-50"><input type="checkbox" checked={targets.includes(choice.versionId)} disabled={!targets.includes(choice.versionId) && targets.length >= 10} onChange={() => toggleTarget(choice.versionId)} className="mt-1 accent-blue-700" /><span><span className="block font-medium text-[#102a43]">{choice.filename}</span><span className="text-xs text-slate-500">{choice.projectTitle} · revision {choice.revision}</span></span></label>)}</div></fieldset>
      </div>}
      {source && targets.length > 0 && <p className="mt-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-900">Selected: <strong>{source.filename}</strong> from <strong>{source.projectTitle}</strong> against {targets.length} selected version(s). Only extracted text is compared; source files remain unchanged.</p>}
      {choices.length >= 2 && <button type="button" disabled={submitting || !sourceId || targets.length === 0} onClick={() => void submit()} className="mt-5 rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300">{submitting ? 'Starting comparison…' : 'Compare selected versions'}</button>}
    </div>
    <section className="mt-8"><h2 className="text-lg font-semibold text-[#102a43]">Comparison history</h2>{jobs.length === 0 && !loading ? <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center"><ScanSearch className="mx-auto text-blue-700" /><p className="mt-3 text-sm text-slate-600">Your selected-source comparison reports will appear here.</p></div> : <div className="mt-3 space-y-3">{jobs.map((job) => <Link key={job.id} href={`/dashboard/similarity/${job.id}`} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 hover:border-blue-300"><div><p className="font-medium text-[#102a43]">{job.source_document_title}</p><p className="mt-1 text-xs text-slate-500">{job.source_project_title} · {job.completed_targets}/{job.total_targets} comparisons</p></div><div className="flex items-center gap-3"><StatusBadge status={job.status} />{['queued','processing'].includes(job.status) && <span className="text-xs text-slate-500">{job.progress}%</span>}<ArrowRight size={16} /></div></Link>)}</div>}</section>
    <p className="mt-8 text-xs leading-5 text-slate-500">Similarity is not proof of plagiarism or misconduct and is not equivalent to Turnitin. No external scholarly or internet coverage is included.</p>
  </ResearchWorkspace>;
}
