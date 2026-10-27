'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ArrowLeft, ShieldCheck, Sparkles } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { researchRequest, type Project, type ResearchDocument } from '@/lib/research';
import { startAnalysis } from '@/lib/intelligence';
import { analysisStartError } from '@/lib/analysis-navigation';

export default function StartAnalysisPage() {
  const { id, documentId } = useParams<{ id: string; documentId: string }>();
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [document, setDocument] = useState<ResearchDocument | null>(null);
  const [profile, setProfile] = useState('general');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    void Promise.all([
      researchRequest<ResearchDocument>(`documents/${documentId}/`),
      researchRequest<Project>(`projects/${id}/`),
    ]).then(([value, projectValue]) => {
      if (live && value.project === id) { setDocument(value); setProject(projectValue); }
      else if (live) setError('This document does not belong to the selected project.');
    }).catch((e) => live && setError(e instanceof Error ? e.message : 'Could not load this manuscript.'));
    return () => { live = false; };
  }, [documentId, id]);
  const version = document?.current_version;

  async function submit() {
    if (!version || !consent) return;
    setBusy(true); setError('');
    try {
      const job = await startAnalysis(documentId, version.id, profile, crypto.randomUUID());
      router.push(`/dashboard/analyses/${job.id}`);
    } catch (e) {
      setError(analysisStartError(e));
    } finally { setBusy(false); }
  }

  return <ResearchWorkspace title="Analyze manuscript">
    <Link href={`/dashboard/projects/${id}/documents/${documentId}`} className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-blue-700"><ArrowLeft size={16} />Back to manuscript</Link>
    <section className="mt-5 max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 sm:p-8">
      <div className="flex items-start gap-4"><span className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><Sparkles /></span><div><p className="text-sm font-semibold uppercase tracking-widest text-blue-700">Evidence-led review</p><h2 className="mt-1 text-xl font-semibold text-[#102a43]">{document?.original_filename ?? 'Loading manuscript…'}</h2><p className="mt-1 text-sm font-medium text-slate-600">Project: {project?.title ?? 'Loading project…'}</p><p className="mt-2 text-sm leading-6 text-slate-600">Scholivyn reviews extracted sections asynchronously and links each finding to source text. It does not rewrite or replace your manuscript.</p></div></div>
      {version && <div className="mt-5 flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 p-3"><StatusBadge status={version.processing_status} /><span className="text-sm text-slate-600">Revision {version.revision_number}</span></div>}
      {version && ['pending', 'processing'].includes(version.processing_status) && <p role="status" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Document extraction is still {version.processing_status}. Return to the manuscript page after processing finishes; analysis can only start after extraction completes.</p>}
      {version?.processing_status === 'failed' && <div role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900"><p className="font-medium">Document extraction failed.</p><p className="mt-1">{version.extraction_metadata.error ?? 'Upload a valid PDF, DOCX or TXT manuscript and wait for extraction to finish.'}</p><Link href={`/dashboard/projects/${id}/documents/${documentId}`} className="mt-3 inline-flex rounded-lg border border-rose-300 px-3 py-2 text-sm font-semibold hover:bg-rose-100">Review manuscript and upload a new version</Link></div>}
      <label className="mt-6 block text-sm font-medium text-slate-700" htmlFor="review-profile">Review discipline</label>
      <select id="review-profile" value={profile} onChange={(e) => setProfile(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-800 focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-100"><option value="general">General academic research</option><option value="computer_science">Computer Science</option><option value="artificial_intelligence">Artificial Intelligence / ML</option></select>
      <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="flex items-center gap-2 text-sm font-semibold text-[#102a43]"><ShieldCheck size={17} className="text-teal-700" />Privacy and provider notice</p><p className="mt-2 text-sm leading-6 text-slate-600">If configured, extracted manuscript text will be sent to the server-selected AI provider for this review. The text is not public. Provider/model details appear in your report; AI feedback is not external citation verification or a substitute for expert review.</p><label className="mt-3 flex cursor-pointer items-start gap-3 text-sm leading-5 text-slate-700"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 h-4 w-4 rounded border-slate-300 accent-blue-700" />I consent to sending this manuscript revision to the configured AI provider for analysis.</label></div>
      {error && <div role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"><p>{error}</p><Link href="/dashboard/analyses" className="mt-2 inline-flex font-semibold text-rose-900 underline underline-offset-2 hover:text-rose-700">Open analysis history</Link></div>}
      <button type="button" onClick={submit} disabled={busy || !consent || version?.processing_status !== 'completed'} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-600">{busy ? 'Queueing review…' : 'Start academic review'}<Sparkles size={16} /></button>
    </section>
  </ResearchWorkspace>;
}
