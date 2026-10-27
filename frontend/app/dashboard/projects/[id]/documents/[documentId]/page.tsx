'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ChangeEvent, useCallback, useEffect, useState } from 'react';
import { ArrowLeft, FileText, UploadCloud, Sparkles } from 'lucide-react';
import { ResearchWorkspace, StatusBadge } from '@/components/research-workspace';
import { researchRequest, reprocessDocumentVersion, retryDocumentExtraction, sourceParagraphElementId, uploadResearchDocument, type ExtractedSection, type ResearchDocument, type SourceParagraph, type Version } from '@/lib/research';

export default function DocumentPage() {
  const { id, documentId } = useParams<{ id: string; documentId: string }>();
  const [document, setDocument] = useState<ResearchDocument | null>(null); const [error, setError] = useState(''); const [active, setActive] = useState('');
  const [selectedVersionId, setSelectedVersionId] = useState(''); const [reprocessing, setReprocessing] = useState(false);
  const [uploading, setUploading] = useState(false); const [progress, setProgress] = useState(0);
  const load = useCallback(async () => { try { const doc = await researchRequest<ResearchDocument>(`documents/${documentId}/`); setDocument(doc); const requestedVersion = new URLSearchParams(window.location.search).get('version'); setSelectedVersionId((current) => current && doc.versions.some((item) => item.id === current) ? current : (doc.versions.find((item) => item.id === requestedVersion)?.id ?? doc.current_version?.id ?? '')); } catch (e) { setError(e instanceof Error ? e.message : 'Could not load this document.'); } }, [documentId]);
  useEffect(() => { const timer = window.setTimeout(() => { void load(); }, 0); return () => window.clearTimeout(timer); }, [load]);
  useEffect(() => { if (!['pending', 'processing'].includes(document?.current_version?.processing_status ?? '')) return; const timer = setInterval(() => void load(), 2000); return () => clearInterval(timer); }, [document, load]);
  const version = document?.versions.find((item) => item.id === selectedVersionId) ?? document?.current_version;
  const versionId = version?.id;
  const sections = version?.extraction_metadata.sections ?? [];
  useEffect(() => {
    if (!versionId || !window.location.hash) return;
    let anchor: string;
    try { anchor = decodeURIComponent(window.location.hash.slice(1)); } catch { return; }
    const frame = window.requestAnimationFrame(() => window.document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'center' }));
    return () => window.cancelAnimationFrame(frame);
  }, [versionId]);
  const jump = (value: ExtractedSection | string) => { const section = typeof value === 'string' ? sections.find((item) => item.title === value) : value; const key = section?.section_key ?? (typeof value === 'string' ? value : value.title); const anchor = typeof value === 'string' ? key : (value.section_key ?? value.title); setActive(key); window.document.getElementById(`section-${anchor}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  async function newVersion(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]; event.currentTarget.value = '';
    if (!file) return; setUploading(true); setProgress(0); setError('');
    try { const updated = await uploadResearchDocument(id, file, documentId, setProgress); setSelectedVersionId(updated.current_version?.id ?? ''); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not upload a new version.'); }
    finally { setUploading(false); }
  }
  async function reprocess() {
    if (!version) return;
    setReprocessing(true); setError('');
    try { const next = await reprocessDocumentVersion(documentId, version.id); setSelectedVersionId(next.id); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not create an extraction revision.'); }
    finally { setReprocessing(false); }
  }
  async function retryExtraction() {
    if (!version) return;
    setReprocessing(true); setError('');
    try { const result = await retryDocumentExtraction(documentId, version.id); setSelectedVersionId(result.id); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not retry document extraction.'); await load(); }
    finally { setReprocessing(false); }
  }
  function renderRecord(record: SourceParagraph, section: ExtractedSection) {
    const index = record.paragraph_index ?? 0;
    const idValue = sourceParagraphElementId(section, index);
    return <p id={idValue} key={idValue} className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{record.text}</p>;
  }
  function renderSection(section: ExtractedSection) {
    const key = section.section_key ?? section.title;
    return <section id={`section-${key}`} key={key} className="scroll-mt-6 border-b border-slate-100 pb-6 last:border-0" style={{ marginInlineStart: `${Math.max(0, (section.level ?? 1) - 1) * 16}px` }}>
      <h2 className="mb-3 text-lg font-semibold text-[#102a43]">{section.title}{section.numbering ? <span className="ml-2 text-xs font-normal text-slate-500">{section.category ?? 'unclassified'}</span> : null}</h2>
      {section.content_blocks?.length ? section.content_blocks.map((block, blockIndex) => block.type === 'paragraph'
        ? renderRecord(block.record, section)
        : <div key={`table-${block.table_order}-${blockIndex}`} className="my-4 overflow-x-auto"><table className="min-w-full border-collapse text-sm"><tbody>{block.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex} className="border border-slate-200 p-2 align-top">{cell.map((record) => renderRecord(record, section))}</td>)}</tr>)}</tbody></table></div>)
        : section.paragraphs.map((paragraph, index) => <p key={`${index}-${paragraph.slice(0, 20)}`} className="mb-3 whitespace-pre-wrap text-sm leading-7 text-slate-700">{paragraph}</p>)}
    </section>;
  }
  return <ResearchWorkspace title={document?.original_filename ?? 'Document'}>
    <Link href={`/dashboard/projects/${id}`} className="inline-flex items-center gap-2 text-sm text-slate-600 hover:text-blue-700"><ArrowLeft size={16} />Back to project</Link>
    {error && <p role="alert" className="mt-5 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{error}</p>}
    {version && ['pending', 'processing', 'failed'].includes(version.processing_status) && <section className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4"><p className="font-medium text-amber-950">Extraction status: {version.processing_status}</p><p className="mt-1 text-sm text-amber-900">{version.processing_error || (version.processing_status === 'processing' ? 'If this has been running for a long time, retry will be enabled after the stale-task timeout.' : 'The original file is retained. Retry queues extraction for this same version.')}</p><button type="button" disabled={reprocessing} onClick={() => void retryExtraction()} className="mt-3 rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-semibold text-amber-950 hover:bg-amber-100 disabled:opacity-60">{reprocessing ? 'Queueing extraction…' : 'Retry extraction'}</button></section>}
    {version?.extraction_metadata.notes?.length ? <details className="mt-4 rounded-lg border border-slate-200 bg-white p-4"><summary className="cursor-pointer text-sm font-semibold text-[#102a43]">Footnotes and endnotes ({version.extraction_metadata.notes.length})</summary><div className="mt-3 space-y-2">{version.extraction_metadata.notes.map((note) => <p key={`${note.kind}-${note.id}`} className="text-sm leading-6 text-slate-700"><span className="mr-2 text-xs uppercase text-slate-500">{note.kind} {note.id}</span>{note.text}</p>)}</div></details> : null}
    {version && sections.length > 0 && <nav aria-label="Extracted section hierarchy" className="mt-4 flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-3">{sections.map((section, index) => <button key={section.section_key ?? `${section.title}-${index}`} type="button" onClick={() => jump(section)} style={{ marginInlineStart: `${Math.max(0, (section.level ?? 1) - 1) * 12}px` }} className="rounded-md border border-slate-200 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50">{section.title}</button>)}</nav>}
    {version && <section aria-label="Extraction revisions" className="mt-5 rounded-xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-[#102a43]">Version {version.revision_number}</h2><p className="text-xs text-slate-500">{version.extraction_algorithm} · {version.processing_status}</p></div><div className="flex flex-wrap gap-2">{version.processing_status === 'completed' && <button type="button" disabled={reprocessing} onClick={() => void reprocess()} className="rounded-lg border border-teal-300 px-3 py-2 text-sm font-semibold text-teal-800 hover:bg-teal-50 disabled:opacity-60">{reprocessing ? 'Creating revision…' : 'Reprocess extraction'}</button>}{version.processing_status === 'completed' && <Link href={`/dashboard/projects/${id}/documents/${documentId}/analysis`} className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-800">Analyze paper with AI</Link>}</div></div><div className="mt-3 flex flex-wrap gap-2">{(document?.versions ?? []).map((item) => <button type="button" key={item.id} aria-pressed={item.id === version.id} onClick={() => setSelectedVersionId(item.id)} className={`rounded-md border px-3 py-1.5 text-xs ${item.id === version.id ? 'border-blue-600 bg-blue-50 text-blue-900' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}>Version {item.revision_number} · {item.processing_status}</button>)}</div></section>}
    {version?.extraction_metadata.coverage && <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-700"><p className="font-medium">Extraction coverage: {version.extraction_metadata.coverage.coverage_percent === null ? 'incomplete (unsupported elements detected)' : `${version.extraction_metadata.coverage.coverage_percent}% of extracted text blocks assigned`}</p><p className="mt-1 text-xs text-slate-500">{version.extraction_metadata.coverage.detected_headings} headings · {version.extraction_metadata.coverage.top_level_sections} top-level sections · {version.extraction_metadata.coverage.subsections} subsections · {version.extraction_metadata.coverage.unclassified_blocks} unclassified blocks</p>{version.extraction_metadata.warnings?.map((warning, index) => <p key={index} className="mt-2 text-xs text-amber-800">{warning}</p>)}</section>}
    {version && <><div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4"><div className="flex items-center gap-3"><FileText className="text-blue-700" /><div><p className="font-medium text-[#102a43]">Version {version.revision_number}</p><p className="text-xs text-slate-500">{(version.file_size / 1024).toFixed(1)} KB · {new Date(version.uploaded_at).toLocaleString()}</p></div></div><div className="flex flex-wrap items-center gap-3"><StatusBadge status={version.processing_status} /><label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"><input type="file" accept=".pdf,.docx,.txt" disabled={uploading} onChange={newVersion} className="sr-only" /><UploadCloud size={16} />{uploading ? `${progress}%` : 'Upload new version'}</label>{version.processing_status === 'completed' && <Link href={`/dashboard/projects/${id}/documents/${documentId}/analysis`} className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white transition hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-700 focus-visible:ring-offset-2"><Sparkles size={16} />Analyze paper with AI</Link>}</div></div>
      {version.processing_status === 'failed' && <p role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">{version.extraction_metadata.error ?? 'Document extraction failed. Please try uploading a valid file.'}</p>}
      {version.processing_status === 'completed' && <div className="mt-5 grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="h-fit rounded-xl border border-slate-200 bg-white p-4"><h2 className="text-sm font-semibold text-[#102a43]">Document sections</h2>{sections.length ? <nav aria-label="Extracted sections" className="mt-3 space-y-1">{sections.map((section) => <button key={section.title} onClick={() => jump(section.title)} className={`block w-full rounded-lg px-3 py-2 text-left text-sm ${active === section.title ? 'bg-blue-50 font-medium text-blue-800' : 'text-slate-600 hover:bg-slate-50'}`}>{section.title}</button>)}</nav> : <p className="mt-3 text-sm text-slate-500">No recognized academic headings were found.</p>}
          <h3 className="mt-6 border-t border-slate-100 pt-4 text-sm font-semibold text-[#102a43]">Versions</h3><div className="mt-2 space-y-2">{(document?.versions ?? []).map((v: Version) => <div key={v.id} className="flex items-center justify-between text-xs text-slate-600"><span>Revision {v.revision_number}</span><StatusBadge status={v.processing_status} /></div>)}</div>
        </aside>
        <div className="min-w-0 space-y-4">{version.file_extension === '.pdf' && <iframe title="PDF document viewer" src={`/api/research/documents/${documentId}/file?version=${version.id}`} className="h-[75vh] min-h-[520px] w-full rounded-xl border border-slate-200 bg-white" />}<article className="rounded-xl border border-slate-200 bg-white p-5 sm:p-8">{sections.map((section) => renderSection(section))}{!sections.length && <div>{(version.extraction_metadata.paragraphs ?? []).map((p, i) => <p key={i} className="mb-3 whitespace-pre-wrap text-sm leading-7 text-slate-700">{p}</p>)}</div>}</article></div>
      </div>}
      {version.processing_status === 'pending' || version.processing_status === 'processing' ? <div className="mt-5 rounded-xl border border-blue-100 bg-blue-50 p-8 text-center"><p className="font-medium text-blue-900">Your document is being processed</p><p className="mt-2 text-sm text-blue-800">This page will update automatically when text extraction finishes.</p></div> : null}
      {version.processing_status === 'completed' && version.extraction_metadata.reference_section && <p className="mt-4 text-xs text-slate-500">References section identified. Extracted text is shown as provided and is not rewritten.</p>}
    </>}
  </ResearchWorkspace>;
}
