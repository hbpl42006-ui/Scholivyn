import { afterEach, describe, expect, it, vi } from 'vitest';
import { citationSourceHref, createCitationJob, type CitationJob, type CitationItem } from './citations';

afterEach(() => vi.unstubAllGlobals());

const job = { document_version_id:'version-1', project_id:'project-1', document_id:'document-1' } as CitationJob;

describe('citation navigation and request contract', () => {
  it('links evidence to the pinned version and existing source paragraph anchor', () => {
    const item = { section_key:'methods', paragraph_index:7 } as CitationItem;
    expect(citationSourceHref(job, item)).toBe('/dashboard/projects/project-1/documents/document-1?version=version-1#source-methods-7');
  });

  it('creates an authenticated BFF request with explicit style and metadata consent fields', async () => {
    vi.stubGlobal('document', { cookie:'scholivyn_csrf=csrf-value' });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id:'job-1' }), {
      status:201, headers:{ 'Content-Type':'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('crypto', { randomUUID:() => 'request-1' });

    await createCitationJob('version-1', 'apa7', true);

    expect(fetchMock).toHaveBeenCalledWith('/api/research/citations/jobs', expect.objectContaining({
      method:'POST', credentials:'same-origin',
      headers:expect.objectContaining({ 'X-CSRF-Token':'csrf-value' }),
      body:JSON.stringify({ document_version_id:'version-1', client_request_id:'request-1', citation_style:'apa7', metadata_consent:true }),
    }));
  });
});
