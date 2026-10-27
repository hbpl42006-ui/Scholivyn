import { researchRequest } from './research';

export type SimilarityStatus = 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled';
export type SimilarityMatch = {
  id: number; match_type: 'exact' | 'near_duplicate'; similarity: number; source_word_count: number;
  citation_label: 'quoted_or_cited' | 'potentially_unattributed';
  source_section_key: string; source_section_title: string; source_paragraph_id: string; source_paragraph_index: number;
  source_start: number; source_end: number; source_text: string; source_match_text: string; source_before: string; source_after: string; source_filename: string; source_revision: number;
  target_section_key: string; target_section_title: string; target_paragraph_id: string; target_paragraph_index: number;
  target_start: number; target_end: number; target_text: string; target_match_text: string; target_before: string; target_after: string; target_filename: string; target_revision: number;
};
export type SimilarityComparison = {
  id: number; target_version_id: string; target_document_id: string; target_project_id: string; target_document_title: string; target_project_title: string;
  status: string; exact_match_count: number; near_match_count: number; matched_source_words: number;
  matches: SimilarityMatch[];
};
export type SimilarityJob = {
  id: string; source_version_id: string; source_document_id: string; source_project_id: string; source_revision: number; source_document_title: string; source_project_title: string;
  status: SimilarityStatus; progress: number; total_targets: number; completed_targets: number;
  exact_match_count: number; near_match_count: number; matched_source_words: number; source_word_count: number;
  matched_percentage: number; error_message: string; created_at: string; updated_at: string; completed_at: string | null;
  comparisons: SimilarityComparison[];
};

export function listSimilarityJobs() { return researchRequest<SimilarityJob[]>('similarity/'); }
export function getSimilarityJob(id: string) { return researchRequest<SimilarityJob>(`similarity/${id}/`); }
export function deleteSimilarityJob(id: string) {
  return researchRequest<void>(`similarity/${id}/`, { method: 'DELETE' });
}
export function createSimilarityJob(sourceVersionId: string, targetVersionIds: string[], requestId: string) {
  return researchRequest<SimilarityJob>('similarity/', { method: 'POST', body: {
    source_version_id: sourceVersionId, target_version_ids: targetVersionIds, client_request_id: requestId,
  } });
}
export function similarityAction(id: string, action: 'cancel' | 'retry') {
  return researchRequest<SimilarityJob>(`similarity/${id}/${action}/`, { method: 'POST', body: {} });
}

export async function downloadSimilarityReport(id: string) {
  const response = await fetch(`/api/research/similarity/${id}/report`, { credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) throw new Error('The similarity report is not available yet.');
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href; link.download = `scholivyn-similarity-${id}.pdf`; link.click(); URL.revokeObjectURL(href);
}

export function filterSimilarityMatches<T extends SimilarityMatch>(matches: T[], type: string, section: string, minimumSimilarity: number) {
  return matches.filter((match) => (type === 'all' || match.match_type === type)
    && (section === 'all' || match.source_section_title === section)
    && match.similarity >= minimumSimilarity);
}

export function similarityEvidenceHref(projectId: string, documentId: string, versionId: string, sectionKey: string, paragraphIndex: number) {
  const version = new URLSearchParams({ version: versionId }).toString();
  const anchor = sectionKey ? `#${encodeURIComponent(`source-${sectionKey}-${paragraphIndex}`)}` : '';
  return `/dashboard/projects/${projectId}/documents/${documentId}?${version}${anchor}`;
}
