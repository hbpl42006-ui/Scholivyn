'use client';

import Link from 'next/link';
import { ChangeEvent, DragEvent, FormEvent, useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, FileText, Pencil, Trash2, UploadCloud } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { deleteResearchResource, researchRequest, uploadResearchDocument, type Project, type ResearchDocument } from '@/lib/research';
import { documentAnalysisHref, isExtractionComplete } from '@/lib/analysis-navigation';

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>(); const router = useRouter();
  const [project, setProject] = useState<Project | null>(null); const [documents, setDocuments] = useState<ResearchDocument[]>([]);
  const [busy, setBusy] = useState(false); const [progress, setProgress] = useState(0); const [error, setError] = useState('');
  const [editing, setEditing] = useState(false); const [dragging, setDragging] = useState(false);
  const load = useCallback(async () => {
    try { const [p, d] = await Promise.all([researchRequest<Project>(`projects/${id}/`), researchRequest<ResearchDocument[]>(`projects/${id}/documents/`)]); setProject(p); setDocuments(d); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load the project.'); }
  }, [id]);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);
  useEffect(() => { if (!documents.some((d) => ['pending', 'processing'].includes(d.current_version?.processing_status ?? ''))) return; const timer = setInterval(() => void load(), 2500); return () => clearInterval(timer); }, [documents, load]);
  async function upload(file?: File) {
    if (!file) return; setError(''); setProgress(0); setBusy(true);
    try { await uploadResearchDocument(id, file, undefined, setProgress); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Upload failed.'); }
    finally { setBusy(false); }
  }
  function choose(event: ChangeEvent<HTMLInputElement>) { void upload(event.currentTarget.files?.[0]); event.currentTarget.value = ''; }
  function drop(event: DragEvent) { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files?.[0]); }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); setError('');
    try { const updated = await researchRequest<Project>(`projects/${id}/`, { method: 'PATCH', body: { title: form.get('title'), description: form.get('description'), research_field: form.get('research_field'), keywords: String(form.get('keywords') ?? '').split(',').map((x) => x.trim()).filter(Boolean) } }); setProject(updated); setEditing(false); }
    catch (e) { setError(e instanceof Error ? e.message : 'Unable to save project.'); }
  }
  async function removeProject() {
    if (!window.confirm('Delete this project and its uploaded documents? Historical AI reviews are retained and may block deletion.')) return;
    setError('');
    try { if (await deleteResearchResource(`projects/${id}/`, project?.title ?? 'this project')) router.push('/dashboard/projects'); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not delete project.'); }
  }
  async function removeDocument(documentId: string, filename: string) {
    if (!window.confirm(`Delete “${filename}” and its uploaded versions? Historical AI reviews will be preserved and may prevent deletion.`)) return;
    setError('');
    try { if (await deleteResearchResource(`documents/${documentId}/`, filename)) await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not delete document.'); }
  }
  return <ResearchWorkspace title={project?.title ?? 'Project'}>
    <Link href="/dashboard/projects" className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-blue-700"><ArrowLeft size={16} />All projects</Link>
    {error && <p role="alert" className="mt-5 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    {project && <>
      <section className="mt-5 rounded-2xl border border-slate-200 bg-white p-5 sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-widest text-blue-700">{project.research_field || 'Research project'}</p><h2 className="mt-2 text-xl font-semibold text-[#102a43]">{project.title}</h2><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600">{project.description || 'No project description yet.'}</p>{project.keywords.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{project.keywords.map((word) => <span key={word} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">{word}</span>)}</div>}</div><div className="flex gap-2"><button onClick={() => setEditing(!editing)} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"><Pencil size={15} />Edit</button><button onClick={removeProject} className="inline-flex items-center gap-2 rounded-lg border border-rose-200 px-3 py-2 text-sm text-rose-700 hover:bg-rose-50"><Trash2 size={15} />Delete</button></div></div>
        {editing && <form onSubmit={save} className="mt-6 grid gap-4 border-t border-slate-100 pt-5">{[['title','Title',project.title],['research_field','Research field',project.research_field],['keywords','Keywords',project.keywords.join(', ')]].map(([name,label,value]) => <label key={name} className="text-sm font-medium text-slate-700">{label}<input name={name} defaultValue={value} className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" /></label>)}<label className="text-sm font-medium text-slate-700">Description<textarea name="description" rows={3} defaultValue={project.description} className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" /></label><div><button className="rounded-lg bg-[#102a43] px-4 py-2 text-sm font-semibold text-white hover:bg-[#173b5c]">Save changes</button></div></form>}
      </section>
      <section className="mt-7"><div className="mb-4 flex items-center justify-between"><h3 className="font-semibold text-[#102a43]">Documents</h3><span className="text-sm text-slate-500">{documents.length} total</span></div>
        <label onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop} className={`block cursor-pointer rounded-2xl border border-dashed p-7 text-center transition ${dragging ? 'border-blue-500 bg-blue-50' : 'border-slate-300 bg-white hover:border-blue-400'}`}><input type="file" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" className="sr-only" disabled={busy} onChange={choose} /><UploadCloud className="mx-auto text-blue-700" size={25} /><span className="mt-2 block text-sm font-medium text-[#102a43]">{busy ? 'Uploading document…' : 'Drop a PDF, DOCX or TXT file here, or browse'}</span><span className="mt-1 block text-xs text-slate-500">Maximum upload size is configured by the workspace administrator.</span>{busy && <div className="mx-auto mt-4 h-2 max-w-md overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} /></div>}</label>
        {documents.length ? <div className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white"><div className="hidden grid-cols-[minmax(0,1fr)_110px_100px_auto_40px] gap-4 border-b border-slate-100 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500 sm:grid"><span>Document</span><span>Status</span><span>Updated</span><span>Analysis</span><span /></div>{documents.map((doc) => { const status = doc.current_version?.processing_status ?? 'pending'; return <div key={doc.id} className="grid gap-2 border-b border-slate-100 p-4 last:border-0 sm:grid-cols-[minmax(0,1fr)_110px_100px_auto_40px] sm:items-center sm:gap-4"><Link href={`/dashboard/projects/${id}/documents/${doc.id}`} className="flex min-w-0 items-center gap-3"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-600"><FileText size={17} /></span><span className="truncate text-sm font-medium text-[#102a43] hover:text-blue-700">{doc.original_filename}</span></Link><div><StatusBadge status={status} /></div><span className="text-xs text-slate-500">{doc.current_version ? new Date(doc.current_version.uploaded_at).toLocaleDateString() : '—'}</span>{isExtractionComplete(status) ? <Link href={documentAnalysisHref(id, doc.id)} className="inline-flex w-fit items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2">Analyze paper with AI</Link> : status === 'failed' ? <Link href={`/dashboard/projects/${id}/documents/${doc.id}`} className="w-fit rounded-lg border border-rose-200 px-3 py-2 text-sm font-semibold text-rose-700 hover:bg-rose-50">Review extraction issue</Link> : <span className="text-xs text-slate-500">Available after extraction</span>}<button aria-label={`Delete ${doc.original_filename}`} onClick={() => void removeDocument(doc.id, doc.original_filename)} className="justify-self-start rounded p-2 text-slate-500 hover:bg-rose-50 hover:text-rose-700 sm:justify-self-end"><Trash2 size={16} /></button></div>; })}</div> : <p className="mt-4 rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">No documents yet. Upload a manuscript to get started.</p>}
      </section>
    </>}
  </ResearchWorkspace>;
}
