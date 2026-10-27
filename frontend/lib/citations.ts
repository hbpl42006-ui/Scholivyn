import { researchRequest } from './research';

export type CitationJobStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type CitationJob = {
  id: string; document_version_id: string; document_id: string; project_id: string; project_title: string;
  original_filename: string; revision_number: number; client_request_id: string; citation_style: 'auto'|'ieee'|'apa7';
  metadata_consent: boolean; metadata_status: string; status: CitationJobStatus; progress: number;
  citation_count: number; reference_count: number; matched_count: number; unmatched_count: number;
  ambiguous_count: number; incomplete_count: number; error_category: string; error_message: string;
  created_at: string; updated_at: string; completed_at: string | null;
};
export type CitationPage<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type CitationItem = { id: number; style?: string; raw_text?: string; numeric_values?: number[];
  author_keys?: string[]; years?: string[]; title?: string; authors?: string[]; year?: number | null; doi?: string;
  doi_normalized?: string; confidence?: string; match_status?: string; section_key?: string; section_title?: string;
  source_section_key?: string; reference_number?: number | null;
  paragraph_id?: string; paragraph_index?: number; start_offset?: number; end_offset?: number;
  code?: string; severity?: string; explanation?: string; source_start?: number | null; source_end?: number | null;
  reference_id?: number | null; citation_id?: number | null; metadata_checks?: { provider: string; status: string; confidence: number | null;
    source_url: string; metadata: Record<string, unknown>; error_category: string }[];
  review_decision?: { decision: string; note: string } | null; excerpt?: string; findings?: string[] };

export async function listCitationJobs() {
  return researchRequest<CitationPage<CitationJob>>('citations/jobs/');
}
export function getCitationJob(id: string) { return researchRequest<CitationJob>(`citations/jobs/${id}/`); }
export function getCitationItems(id: string, kind: 'citations'|'references'|'matches'|'findings', offset = 0) {
  return researchRequest<CitationPage<CitationItem>>(`citations/jobs/${id}/items/?kind=${kind}&limit=100&offset=${offset}`);
}
export function createCitationJob(documentVersionId: string, citationStyle: CitationJob['citation_style'], metadataConsent: boolean) {
  return researchRequest<CitationJob>('citations/jobs/', { method: 'POST', body: {
    document_version_id: documentVersionId, client_request_id: crypto.randomUUID(), citation_style: citationStyle,
    metadata_consent: metadataConsent,
  } });
}
export function citationAction(id: string, action: 'cancel'|'retry'|'verify-metadata', consent = false) {
  return researchRequest<CitationJob>(`citations/jobs/${id}/actions/${action}/`, { method: 'POST', body: { consent } });
}
export function saveCitationDecision(jobId: string, findingId: number, decision: 'accepted'|'rejected'|'needs_review', note = '') {
  return researchRequest(`citations/jobs/${jobId}/findings/${findingId}/decision/`, { method: 'POST', body: { decision, note } });
}
export async function downloadCitationReport(id: string) {
  const response = await fetch(`/api/research/citations/jobs/${id}/report/`, { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) throw new Error('Citation report is not available yet.');
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a'); anchor.href = objectUrl;
  anchor.download = `scholivyn-citations-${id}.pdf`; anchor.click(); URL.revokeObjectURL(objectUrl);
}

export function citationSourceHref(job: CitationJob, item: CitationItem) {
  const version = new URLSearchParams({ version: job.document_version_id });
  const anchor = item.section_key && item.paragraph_index !== undefined
    ? `#source-${item.section_key}-${item.paragraph_index}` : '';
  return `/dashboard/projects/${job.project_id}/documents/${job.document_id}?${version}${anchor}`;
}
