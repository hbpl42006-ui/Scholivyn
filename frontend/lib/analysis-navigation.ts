import { ApiError } from './auth';

export function documentAnalysisHref(projectId: string, documentId: string) {
  return `/dashboard/projects/${projectId}/documents/${documentId}/analysis`;
}

export function isExtractionComplete(status?: string | null) {
  return status === 'completed';
}

export function analysisStartError(error: unknown): string {
  const message = error instanceof Error ? error.message : '';
  const normalized = message.toLowerCase();
  if (normalized.includes('not configured') || normalized.includes('disabled by server')) {
    return 'AI analysis is unavailable until the administrator enables it and configures the provider key and model on the Django server.';
  }
  if (normalized.includes('credit') || normalized.includes('insufficient_quota') || normalized.includes('billing')) {
    return 'The AI provider account has no available credits or has reached its billing limit. Ask the workspace administrator to check provider billing.';
  }
  if (error instanceof ApiError && error.status === 429) {
    if (normalized.includes('already queued or processing') || normalized.includes('already running')) {
      return 'An analysis for your account is already queued or processing. View it in Analysis history and start another after it finishes.';
    }
    const retryMatch = normalized.match(/expected available in\s+(\d+)\s+seconds?/);
    const retrySeconds = error.retryAfterSeconds ?? (retryMatch ? Number(retryMatch[1]) : undefined);
    if (retrySeconds && Number.isFinite(retrySeconds)) {
      const minutes = Math.ceil(retrySeconds / 60);
      const wait = minutes < 1 ? `${retrySeconds} seconds` : `${minutes} minute${minutes === 1 ? '' : 's'}`;
      return `The analysis creation limit has been reached. Try again in about ${wait}. Your existing reviews are available in Analysis history.`;
    }
    return 'The analysis request was rate-limited. Check Analysis history and wait briefly before trying again.';
  }
  if (normalized.includes('queue') || normalized.includes('redis')) {
    return 'The analysis could not be queued. Ask the administrator to check Redis and the AI worker, then try again.';
  }
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Your session has expired. Sign in again, then reopen this manuscript.';
    if (error.status === 403) return 'Your session could not be verified. Refresh the page and try again.';
    if (error.status >= 500) return 'The analysis service is temporarily unavailable. Check the server and AI worker, then try again.';
  }
  return message || 'Could not start the analysis. Check the service status and try again.';
}

export function analysisFailureGuidance(category: string) {
  switch (category) {
    case 'provider_billing':
      return 'The configured AI account has no available credits or its billing limit was reached. Ask the administrator to update provider billing, then start a new analysis.';
    case 'provider_authentication':
      return 'The provider rejected its server credential. Ask the administrator to verify the server-side API key, then start a new analysis.';
    case 'provider_rate_limit':
      return 'Provider capacity is temporarily limited. Completed chunks are saved and the remaining work will resume automatically.';
    case 'provider_quota_unavailable':
      return 'Shared provider quota coordination is unavailable. Saved work will resume after the Redis-backed AI worker recovers.';
    case 'provider_payload_too_large':
      return 'The provider could not accept one manuscript fragment after automatic splitting. Smaller sections may still complete.';
    case 'provider_quota':
      return 'The AI provider project has exhausted its available quota. Check Google AI Studio quotas or wait for the quota reset.';
    case 'provider_model':
      return 'The configured AI model is unavailable to this provider project. Ask the administrator to check the model identifier and access.';
    case 'provider_unavailable':
    case 'provider_server':
      return 'The provider could not complete this request. The worker retries temporary errors; if this analysis has failed, try again later.';
    case 'queue_unavailable':
      return 'The analysis queue could not accept this job. Ask the administrator to check Redis and the AI worker.';
    case 'not_configured':
      return 'AI analysis is not enabled or its provider key/model is missing. Ask the administrator to configure it on the Django server.';
    default:
      return '';
  }
}
