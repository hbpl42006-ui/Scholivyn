import { ApiError } from './auth';
import { researchRequest } from './research';

export type AnalysisStatus = 'queued' | 'processing' | 'waiting_for_quota' | 'completed' | 'partially_completed' | 'failed' | 'cancelled';
export type AnalysisChunkCounts = { total: number; completed: number; failed: number; pending: number };
export type AnalysisJob = {
  id: string; project: string; project_title: string; document: string; document_title: string; document_version: string; analysis_type: string;
  reviewer_profile: string; status: AnalysisStatus; progress: number; started_at: string | null;
  completed_at: string | null; next_attempt_at: string | null; chunk_counts: AnalysisChunkCounts;
  error_category: string; error_message: string; provider: string;
  model_identifier: string; prompt_version: string; input_tokens: number; output_tokens: number; reasoning_tokens: number | null;
  created_at: string; updated_at: string;
};
export type AnalysisSection = {
  id: string; section_title: string; section_category: string; review_summary: string;
  strengths: string[]; weaknesses: string[]; recommendations: string[];
  processing_status: string; completed_chunks: number; failed_chunks: number;
};
export type WritingSuggestion = { id: string; original_text: string; suggested_text: string; explanation: string; status: string; source_paragraph_index: number | null };
export type AnalysisIssue = {
  id: string; section_title: string; section_category: string; section_key: string; category: string; severity: string;
  title: string; explanation: string; evidence_snippet: string; source_paragraph_index: number | null;
  suggested_improvement: string; resolution_status: string; suggestion?: WritingSuggestion | null;
};
export type AnalysisPage<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export function formatReasoningTokenUsage(tokens: number | null): string | null {
  return tokens === null ? null : `${tokens.toLocaleString()} reasoning tokens (included in output)`;
}

export function startAnalysis(documentId: string, versionId: string, profile: string, requestId: string) {
  return researchRequest<AnalysisJob>('analyses/', { body: {
    document_id: documentId, document_version_id: versionId, reviewer_profile: profile,
    consent_to_external_processing: true, client_request_id: requestId,
  } });
}

export function getAnalysis(id: string) { return researchRequest<AnalysisJob>(`analyses/${id}/`); }
export function resumeAnalysis(id: string) { return researchRequest<AnalysisJob>(`analyses/${id}/resume/`, { method: 'POST', body: {} }); }
export function getAnalysisSections(id: string) { return researchRequest<AnalysisSection[]>(`analyses/${id}/sections/`); }
export function getAnalysisIssues(id: string, page = 1) {
  return researchRequest<AnalysisPage<AnalysisIssue>>(`analyses/${id}/issues/?page=${page}&page_size=100`);
}
export function getDocumentAnalyses(id: string) { return researchRequest<AnalysisJob[]>(`documents/${id}/analyses/`); }

export function updateAnalysisIssue(id: string, value: { resolution_status?: string; suggestion_status?: string }) {
  return researchRequest<AnalysisIssue>(`analyses/issues/${id}/`, { method: 'PATCH', body: value });
}

export async function downloadAnalysisReport(id: string): Promise<Blob> {
  await researchRequest<{ download_url: string }>(`analyses/${id}/report/`, { body: {} });
  const response = await fetch(`/api/research/analyses/${id}/report`, { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string };
    throw new ApiError(body.detail ?? 'Could not download the analysis report.', response.status);
  }
  return response.blob();
}
