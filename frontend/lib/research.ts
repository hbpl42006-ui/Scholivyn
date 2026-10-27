import { ApiError } from './auth';

export type Project = {
  id: string; title: string; description: string; research_field: string; keywords: string[];
  status: 'active' | 'on_hold' | 'completed' | 'archived'; created_at: string; updated_at: string; document_count: number;
};
export type Version = {
  id: string; revision_number: number; original_filename: string; file_extension: string; mime_type: string;
  file_size: number; processing_status: 'pending' | 'processing' | 'completed' | 'failed';
  processing_started_at: string | null; processing_error: string; processing_attempt: number;
  extraction_algorithm: string; reprocessed_from: string | null;
  extraction_metadata: {
    extraction_algorithm?: string; pages?: { page: number; text: string }[]; paragraphs?: string[];
    headings?: { title: string; paragraph_index: number; source_id?: string; normalized_category?: string; numbering?: string | null; level?: number; parent_key?: string | null; confidence?: string; signals?: string[] }[];
    sections?: ExtractedSection[]; reference_section?: ExtractedSection | null; metadata?: Record<string, string | number>;
    coverage?: { source_text_blocks: number; extracted_text_blocks: number; detected_headings: number; top_level_sections: number; subsections: number; unclassified_blocks: number; skipped_unsupported_elements: number; duplicate_assignments: number; assigned_blocks: number; coverage_percent: number | null; empty_sections: string[] };
    warnings?: string[]; unclassified?: SourceParagraph[]; tables?: { table_order: number; rows: string[][] }[]; notes?: { kind: string; id: string; text: string }[]; error?: string;
  };
  uploaded_at: string;
};
export type SourceParagraph = { source_id: string; document_order: number; text: string; kind: string; paragraph_index: number | null; table_order?: number | null; row?: number | null; cell?: number | null };
export type ExtractedSection = {
  title: string; normalized_title?: string; category?: string; numbering?: string | null; level?: number; parent_key?: string | null;
  document_order?: number; section_key?: string; confidence?: string; signals?: string[]; unclassified?: boolean;
  paragraphs: string[]; paragraph_records?: SourceParagraph[];
  content_blocks?: ({ type: 'paragraph'; record: SourceParagraph } | { type: 'table'; table_order: number; rows: SourceParagraph[][][] })[];
};
export type ResearchDocument = { id: string; project: string; original_filename: string; current_version: Version | null; versions: Version[]; created_at: string; updated_at: string };

export function sourceParagraphElementId(section: Pick<ExtractedSection, 'section_key' | 'title'>, index: number) {
  const key = section.section_key ?? section.title.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  return `source-${key}-${index}`;
}

function csrf() {
  const value = document.cookie.split('; ').find((item) => item.startsWith('scholivyn_csrf='))?.split('=').slice(1).join('=') ?? '';
  return decodeURIComponent(value);
}

export async function researchRequest<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = options.method ?? (options.body === undefined ? 'GET' : 'POST');
  const routePath = path.replace(/^\/+|\/+$/g, '');
  if (method !== 'GET' && !csrf()) await fetch('/api/auth/csrf', { credentials: 'same-origin' });
  const response = await fetch(`/api/research/${routePath}`, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: { ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(method === 'GET' ? {} : { 'X-CSRF-Token': csrf() }) },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fields = data as Record<string, unknown>;
    const message = typeof fields.detail === 'string' ? fields.detail : Object.values(fields).flatMap((v) => Array.isArray(v) ? v : []).find((v) => typeof v === 'string') as string | undefined;
    const retryAfter = Number(response.headers.get('retry-after'));
    throw new ApiError(
      message ?? 'The request could not be completed.',
      response.status,
      fields as Record<string, unknown>,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    );
  }
  return data as T;
}

type SimilarityRetentionConflict = {
  detail?: string;
  confirmation_required?: boolean;
  blocked_by_other_account?: boolean;
  protected_ai_analysis_count?: number;
  protected_writing_suggestion_count?: number;
  dependent_similarity_reports?: { id: string; source_filename: string; source_project: string; status: string; references: { role: string; filename: string; project: string; revision: number }[] }[];
};

/** Delete a project/document, asking before removing only its owned dependent similarity reports. */
export async function deleteResearchResource(
  path: string,
  label: string,
  confirm: (message: string) => boolean = (message) => window.confirm(message),
) {
  try {
    await researchRequest(path, { method: 'DELETE', body: { delete_dependent_similarity_reports: false } });
    return true;
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 409) throw error;
    const dependency = (error.fields ?? {}) as SimilarityRetentionConflict;
    const reports = dependency.dependent_similarity_reports ?? [];
    if (dependency.protected_ai_analysis_count || dependency.protected_writing_suggestion_count) {
      const reviews = dependency.protected_ai_analysis_count ?? 0;
      const suggestions = dependency.protected_writing_suggestion_count ?? 0;
      throw new Error(`${error.message} ${reviews} historical AI review(s) and ${suggestions} writing suggestion(s) are retained.`);
    }
    if (dependency.blocked_by_other_account || reports.length === 0) throw error;
    const reportList = reports.map((report) => {
      const dependencies = report.references.map((reference) => `${reference.role}: ${reference.filename} v${reference.revision} (${reference.project})`).join('; ');
      return `• ${report.source_filename} report (${report.status}) — depends on ${dependencies}`;
    }).join('\n');
    const approved = confirm(
      `${reports.length} retained similarity report(s) depend on ${label}:\n\n${reportList}\n\n` +
      `If you continue, only these reports that you own and their comparison results will be deleted. ` +
      `Source manuscripts are not deleted as a side effect. Historical AI reviews are always preserved. Continue?`,
    );
    if (!approved) return false;
    await researchRequest(path, { method: 'DELETE', body: { delete_dependent_similarity_reports: true } });
    return true;
  }
}

export async function uploadResearchDocument(projectId: string, file: File, documentId: string | undefined, onProgress: (percent: number) => void) {
  if (!csrf()) await fetch('/api/auth/csrf', { credentials: 'same-origin' });
  return new Promise<ResearchDocument>((resolve, reject) => {
    const csrfValue = csrf();
    const data = new FormData();
    data.append('file', file);
    if (documentId) data.append('document_id', documentId);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/research/projects/${projectId}/documents/upload`);
    xhr.withCredentials = true;
    xhr.setRequestHeader('X-CSRF-Token', csrfValue);
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100)); };
    xhr.onerror = () => reject(new Error('Upload failed. Check your connection and try again.'));
    xhr.onload = () => {
      const payload = JSON.parse(xhr.responseText || '{}');
      if (xhr.status < 200 || xhr.status >= 300) return reject(new ApiError(payload.detail ?? payload.file?.[0] ?? 'Upload failed.', xhr.status, payload));
      resolve(payload as ResearchDocument);
    };
    xhr.send(data);
  });
}

export function reprocessDocumentVersion(documentId: string, versionId: string) {
  return researchRequest<Version>(`documents/${documentId}/versions/${versionId}/reprocess`, { method: 'POST', body: {} });
}

export function retryDocumentExtraction(documentId: string, versionId: string) {
  return researchRequest<Version>(`documents/${documentId}/versions/${versionId}/retry-extraction`, { method: 'POST', body: {} });
}
