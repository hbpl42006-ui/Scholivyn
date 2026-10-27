import { afterEach, describe, expect, it, vi } from 'vitest';
import { deleteResearchResource } from './research';

afterEach(() => vi.unstubAllGlobals());

describe('research retention confirmation', () => {
  it('shows the exact dependent version and retries only after explicit confirmation', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=test-token' });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        detail: 'Retained reports depend on this document.',
        confirmation_required: true,
        blocked_by_other_account: false,
        protected_ai_analysis_count: 0,
        protected_writing_suggestion_count: 0,
        dependent_similarity_reports: [{ id: 'report-id', source_filename: 'source.docx', source_project: 'Project', status: 'completed', references: [{ role: 'comparison target', filename: 'target.docx', project: 'Project', revision: 2 }] }],
      }), { status: 409, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    const confirm = vi.fn<(message: string) => boolean>(() => true);

    await expect(deleteResearchResource('documents/document-id/', 'target.docx', confirm)).resolves.toBe(true);
    expect(confirm).toHaveBeenCalledOnce();
    expect(confirm.mock.calls[0][0]).toContain('target.docx v2');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toEqual({ delete_dependent_similarity_reports: true });
  });

  it('never retries deletion when retained AI history blocks the request', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=test-token' });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: 'This manuscript has retained AI review history.',
      protected_ai_analysis_count: 1,
      protected_writing_suggestion_count: 0,
      dependent_similarity_reports: [],
    }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(deleteResearchResource('documents/document-id/', 'target.docx', vi.fn())).rejects.toThrow('1 historical AI review(s)');
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
