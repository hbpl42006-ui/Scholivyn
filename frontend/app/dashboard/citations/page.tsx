'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpenCheck, CircleAlert } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { researchRequest, type Project, type ResearchDocument } from '@/lib/research';
import { createCitationJob, listCitationJobs, type CitationJob } from '@/lib/citations';

type VersionChoice = { id: string; documentId: string; projectId: string; project: string; filename: string; revision: number };

export default function CitationsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<CitationJob[]>([]);
  const [versions, setVersions] = useState<VersionChoice[]>([]);
  const [selectedVersion, setSelectedVersion] = useState('');
  const [style, setStyle] = useState<CitationJob['citation_style']>('auto');
  const [metadataConsent, setMetadataConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    void Promise.all([listCitationJobs(), researchRequest<Project[]>('projects/')]).then(async ([history, projects]) => {
      const grouped = await Promise.all(projects.map(async (project) => ({ project,
        documents: await researchRequest<ResearchDocument[]>(`projects/${project.id}/documents/`) })));
      if (!live) return;
      const choices = grouped.flatMap(({ project, documents }) => documents.flatMap((document) => {
        const candidates = document.versions.length ? document.versions : document.current_version ? [document.current_version] : [];
        return candidates.filter((version) => version.processing_status === 'completed').map((version) => ({
          id: version.id, documentId: document.id, projectId: project.id, project: project.title,
          filename: version.original_filename, revision: version.revision_number,
        }));
      }));
      setVersions(choices); setSelectedVersion(choices[0]?.id ?? ''); setJobs(history.results);
    }).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Could not load your manuscripts.'))
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  const selected = versions.find((row) => row.id === selectedVersion);
  async function submit() {
    if (!selectedVersion) return;
    setSubmitting(true); setError('');
    try {
      const job = await createCitationJob(selectedVersion, style, metadataConsent);
      router.push(`/dashboard/citations/${job.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start citation analysis.'); setSubmitting(false);
    }
  }

  return <ResearchWorkspace title="Citation & reference check">
    <section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-7">
      <p className="text-xs font-semibold uppercase tracking-widest text-blue-700">Version-pinned structural review</p>
      <h2 className="mt-2 text-xl font-semibold text-[#102a43]">Reconcile citations and references</h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Scholivyn checks citation-to-bibliography links, duplicates, incomplete parsed details, and selected IEEE/APA 7 structure. It does not determine whether a source is authentic or whether misconduct occurred.</p>
      {error && <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
      {loading ? <p className="mt-5 text-sm text-slate-500">Loading completed manuscript versions…</p> : versions.length === 0 ?
        <div className="mt-5 rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-600">No completed manuscript versions are available. Finish document extraction first.</div> :
        <div className="mt-5 max-w-3xl space-y-4">
          <label className="block text-sm font-medium text-slate-700">Manuscript version
            <select value={selectedVersion} onChange={(event) => setSelectedVersion(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-300 bg-white p-3">
              {versions.map((row) => <option key={row.id} value={row.id}>{row.filename} · {row.project} · v{row.revision}</option>)}
            </select>
          </label>
          {selected && <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">Selected: <strong>{selected.filename}</strong> · {selected.project} · revision {selected.revision}. The report stays pinned to this exact extraction version.</p>}
          <label className="block text-sm font-medium text-slate-700">Citation style
            <select value={style} onChange={(event) => setStyle(event.target.value as CitationJob['citation_style'])} className="mt-2 w-full rounded-lg border border-slate-300 bg-white p-3">
              <option value="auto">Detect supported style</option><option value="ieee">IEEE numeric</option><option value="apa7">APA 7 author-year</option>
            </select>
          </label>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <p className="flex items-center gap-2 font-semibold text-[#102a43]"><CircleAlert size={17} className="text-teal-700" />Optional external metadata check</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">If selected, only parsed DOI and reference title/author/year fields are sent to Crossref and OpenAlex. Manuscript paragraphs and full text are never sent. Provider records can be incomplete or mismatched and are not proof of anything.</p>
            <label className="mt-3 flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" checked={metadataConsent} onChange={(event) => setMetadataConsent(event.target.checked)} className="mt-1 accent-blue-700" />I consent to these metadata-only lookups for this analysis.</label>
          </div>
          <button type="button" disabled={submitting || !selectedVersion} onClick={() => void submit()} className="rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300">{submitting ? 'Starting check…' : 'Check citations and references'}</button>
        </div>}
    </section>

    <section className="mt-8"><h2 className="text-lg font-semibold text-[#102a43]">Analysis history</h2>
      {jobs.length === 0 && !loading ? <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center"><BookOpenCheck className="mx-auto text-blue-700" /><p className="mt-3 text-sm text-slate-600">Your citation checks will appear here.</p></div> :
        <div className="mt-3 space-y-3">{jobs.map((job) => <Link key={job.id} href={`/dashboard/citations/${job.id}`} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 hover:border-blue-300"><span><span className="block font-medium text-[#102a43]">{job.original_filename}</span><span className="mt-1 block text-xs text-slate-500">{job.project_title} · v{job.revision_number} · {job.citation_count} citations / {job.reference_count} references</span></span><span className="flex items-center gap-3"><StatusBadge status={job.status} />{job.status === 'processing' && <span className="text-xs text-slate-500">{job.progress}%</span>}</span></Link>)}</div>}
    </section>
    <p className="mt-8 text-xs leading-5 text-slate-500">A matching result means a parsed citation key links to a parsed bibliography item. Metadata lookup results are candidates from external registries, not a citation-authenticity score.</p>
  </ResearchWorkspace>;
}
