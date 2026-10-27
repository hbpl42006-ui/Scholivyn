import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatReasoningTokenUsage, resumeAnalysis, startAnalysis, updateAnalysisIssue } from './intelligence';
import { analysisFailureGuidance, analysisStartError, documentAnalysisHref, isExtractionComplete } from './analysis-navigation';
import { ApiError } from './auth';

describe('research intelligence API client', () => {
  afterEach(() => vi.restoreAllMocks());

  it('labels reasoning tokens as a breakdown of output and keeps unavailable detail unknown', () => {
    expect(formatReasoningTokenUsage(1234)).toMatch(/1,234 reasoning tokens \(included in output\)/);
    expect(formatReasoningTokenUsage(null)).toBeNull();
  });

  it('sends explicit external processing consent and request id through the authenticated BFF', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=csrf-value' });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'job-1', status: 'queued' }), { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    await startAnalysis('doc-1', 'version-1', 'general', 'request-1');
    expect(fetchMock).toHaveBeenCalledWith('/api/research/analyses', expect.objectContaining({
      method: 'POST', credentials: 'same-origin',
      body: JSON.stringify({ document_id: 'doc-1', document_version_id: 'version-1', reviewer_profile: 'general', consent_to_external_processing: true, client_request_id: 'request-1' }),
    }));
  });

  it('uses PATCH to record a suggestion decision without editing manuscript text', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=csrf-value' });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'issue-1', resolution_status: 'accepted' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await updateAnalysisIssue('issue-1', { suggestion_status: 'accepted' });
    expect(fetchMock).toHaveBeenCalledWith('/api/research/analyses/issues/issue-1', expect.objectContaining({ method: 'PATCH' }));
  });

  it('resumes saved analysis through the authenticated API without creating a new job', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=csrf-value' });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'job-1', status: 'waiting_for_quota', progress: 35,
    }), { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    await resumeAnalysis('job-1');
    expect(fetchMock).toHaveBeenCalledWith('/api/research/analyses/job-1/resume', expect.objectContaining({
      method: 'POST', credentials: 'same-origin', body: '{}',
    }));
  });

  it('preserves retry timing from throttled API responses', async () => {
    vi.stubGlobal('document', { cookie: 'scholivyn_csrf=csrf-value' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Request was throttled. Expected available in 62 seconds.' }),
      { status: 429, headers: { 'content-type': 'application/json', 'retry-after': '62' } },
    )));
    await expect(startAnalysis('doc-1', 'version-1', 'general', 'request-2'))
      .rejects.toMatchObject({ status: 429, retryAfterSeconds: 62 });
  });

  it('routes completed manuscripts into the existing consent screen and gates incomplete extraction', () => {
    expect(documentAnalysisHref('project-1', 'document-1')).toBe('/dashboard/projects/project-1/documents/document-1/analysis');
    expect(isExtractionComplete('completed')).toBe(true);
    expect(isExtractionComplete('processing')).toBe(false);
    expect(isExtractionComplete('failed')).toBe(false);
  });

  it('provides actionable setup, billing, queue and session guidance', () => {
    expect(analysisStartError(new Error('AI analysis is not configured.'))).toMatch(/administrator.*provider key and model/i);
    expect(analysisStartError(new ApiError('An analysis is already queued or processing for this account.', 429))).toMatch(/already queued or processing/i);
    expect(analysisStartError(new ApiError('Request was throttled. Expected available in 1132 seconds.', 429, undefined, 1132))).toMatch(/try again in about 19 minutes/i);
    expect(analysisStartError(new Error('The queue is temporarily unavailable.'))).toMatch(/Redis and the AI worker/i);
    expect(analysisFailureGuidance('provider_billing')).toMatch(/credits|billing/i);
    expect(analysisFailureGuidance('provider_quota')).toMatch(/Google AI Studio quotas/i);
    expect(analysisFailureGuidance('provider_model')).toMatch(/model identifier/i);
  });
});
