import logging
import math
import random
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q, Sum
from django.utils import timezone

from apps.intelligence.models import AIUsageRecord, AnalysisChunkResult, AnalysisJob
from apps.billing.models import CreditReservation
from apps.billing.services.entitlements import finalize_usage, mark_provider_started, release_reservation
from apps.intelligence.services.providers.base import AIProviderError
from apps.intelligence.services.review_orchestrator import execute_job

logger = logging.getLogger(__name__)

_CHUNK_FAILURE_MESSAGES = {
    'provider_invalid_argument': 'The AI provider rejected an analysis request argument. Check the model configuration.',
    'provider_schema': 'The AI provider rejected the structured response schema.',
    'provider_model': 'The configured AI model is unavailable.',
    'provider_authentication': 'AI provider access was denied. Check server-side credentials and permissions.',
    'provider_billing': 'The AI provider account has a billing restriction or depleted credits.',
    'provider_quota': 'The AI provider has exhausted its available quota.',
    'provider_rate_limit': 'Analysis is waiting for provider capacity. Completed sections are saved.',
    'provider_quota_unavailable': 'Shared quota coordination is unavailable; analysis will resume when it recovers.',
    'provider_payload_too_large': 'A manuscript section could not be reduced to fit provider request limits.',
    'provider_unavailable': 'The AI provider is temporarily unavailable.',
}


def _chunk_failure_summary(job_id):
    category = AnalysisChunkResult.objects.filter(
        job_id=job_id, status=AnalysisChunkResult.Status.FAILED,
    ).exclude(error_category='').order_by('error_category').values_list('error_category', flat=True).first()
    if not category:
        return '', ''
    message = _CHUNK_FAILURE_MESSAGES.get(
        category, 'One or more manuscript sections could not be analyzed. Review section errors and retry if appropriate.',
    )
    return category[:40], message[:240]


def _progress_for(job_id):
    chunks = AnalysisChunkResult.objects.filter(job_id=job_id).exclude(status=AnalysisChunkResult.Status.SUPERSEDED)
    total = chunks.count()
    completed = chunks.filter(status=AnalysisChunkResult.Status.COMPLETED).count()
    return min(99, int(completed * 100 / max(1, total)))


def _settle_billing(job_id, *, completed=False):
    reservation = CreditReservation.objects.filter(reference_type='analysis_job', reference_id=str(job_id)).first()
    if not reservation:
        return
    totals = AIUsageRecord.objects.filter(job_id=job_id).aggregate(
        input=Sum('input_tokens'), output=Sum('output_tokens'), reasoning=Sum('reasoning_tokens'))
    inputs, outputs = totals['input'] or 0, totals['output'] or 0
    if completed or inputs or outputs:
        finalize_usage(reservation, event_key=f'ai-analysis:{job_id}', units=1,
            input_tokens=inputs, output_tokens=outputs, reasoning_tokens=totals['reasoning'])
    else:
        release_reservation(reservation, uncertain=bool(reservation.provider_started_at))


def _retry_delay(exc, job_id):
    if exc.retry_after_seconds is not None:
        # Provider Retry-After/reset is authoritative; never retry earlier than requested.
        minimum = max(1, int(math.ceil(exc.retry_after_seconds)))
        positive_jitter = random.uniform(0, min(5, max(1, minimum * 0.1)))
        return minimum + int(math.ceil(positive_jitter))
    retry_number = max(1, AnalysisChunkResult.objects.filter(job_id=job_id).order_by('-retry_count')
                       .values_list('retry_count', flat=True).first() or 1)
    ceiling = max(1, int(settings.AI_RETRY_MAX_DELAY))
    base = min(ceiling, int(settings.AI_RETRY_BASE_DELAY) * (2 ** min(retry_number - 1, 10)))
    return min(ceiling, max(1, int(random.uniform(base * 0.75, base * 1.25))))


def _schedule_watchdog(task, job_id, delay):
    delivery = getattr(task.request, 'delivery_info', None) or {}
    if delivery and not settings.CELERY_TASK_ALWAYS_EAGER:
        task.apply_async(args=(str(job_id),), countdown=max(1, delay), queue='ai')


@shared_task(bind=True, max_retries=3, acks_late=True, reject_on_worker_lost=True,
            name='intelligence.process_analysis_job', queue='ai')
def process_analysis_job(self, job_id):
    close_old_connections()
    try:
        now = timezone.now()
        job = AnalysisJob.objects.get(pk=job_id)
        terminal = (AnalysisJob.Status.COMPLETED, AnalysisJob.Status.PARTIALLY_COMPLETED,
                    AnalysisJob.Status.FAILED, AnalysisJob.Status.CANCELLED)
        if job.status in terminal:
            return {'status': job.status}
        if job.status == AnalysisJob.Status.WAITING_FOR_QUOTA and job.next_attempt_at and job.next_attempt_at > now:
            _schedule_watchdog(self, job_id, (job.next_attempt_at - now).total_seconds())
            return {'status': job.status}
        if job.status == AnalysisJob.Status.PROCESSING and job.processing_lease_until and job.processing_lease_until > now:
            _schedule_watchdog(self, job_id, (job.processing_lease_until - now).total_seconds())
            return {'status': 'already_processing'}

        lease_until = now + timedelta(seconds=settings.AI_WORKER_LEASE_SECONDS)
        claimable = Q(status=AnalysisJob.Status.QUEUED) | Q(
            status=AnalysisJob.Status.WAITING_FOR_QUOTA,
        ) & (Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)) | Q(
            status=AnalysisJob.Status.PROCESSING,
        ) & (Q(processing_lease_until__isnull=True) | Q(processing_lease_until__lte=now))
        acquired = AnalysisJob.objects.filter(pk=job_id).filter(claimable).update(
            status=AnalysisJob.Status.PROCESSING, started_at=job.started_at or now,
            processing_lease_until=lease_until, next_attempt_at=None,
            error_category='', error_message='',
        )
        if not acquired:
            return {'status': AnalysisJob.objects.get(pk=job_id).status}
        _schedule_watchdog(self, job_id, settings.AI_WORKER_LEASE_SECONDS)
        job.refresh_from_db()
        reservation = CreditReservation.objects.filter(reference_type='analysis_job', reference_id=str(job_id)).first()
        mark_provider_started(reservation)

        def set_progress(value):
            AnalysisJob.objects.filter(pk=job_id, status=AnalysisJob.Status.PROCESSING).update(
                progress=value,
                processing_lease_until=timezone.now() + timedelta(seconds=settings.AI_WORKER_LEASE_SECONDS),
            )

        def cancelled():
            return AnalysisJob.objects.filter(pk=job_id, status=AnalysisJob.Status.CANCELLED).exists()

        try:
            result = execute_job(job, set_progress, cancelled)
            if result == 'cancelled' or cancelled():
                AnalysisJob.objects.filter(pk=job_id).update(
                    status=AnalysisJob.Status.CANCELLED, completed_at=timezone.now(),
                    processing_lease_until=None, next_attempt_at=None,
                )
                _settle_billing(job_id)
                return {'status': AnalysisJob.Status.CANCELLED}
            error_category, error_message = ('', '')
            if result in (AnalysisJob.Status.FAILED, AnalysisJob.Status.PARTIALLY_COMPLETED):
                error_category, error_message = _chunk_failure_summary(job_id)
            AnalysisJob.objects.filter(pk=job_id).update(
                status=result, progress=100 if result == AnalysisJob.Status.COMPLETED else _progress_for(job_id),
                completed_at=timezone.now(), processing_lease_until=None, next_attempt_at=None,
                error_category=error_category, error_message=error_message,
            )
            _settle_billing(job_id, completed=result == AnalysisJob.Status.COMPLETED)
            return {'status': result}
        except AIProviderError as exc:
            checkpointed_retry = AnalysisChunkResult.objects.filter(
                job_id=job_id, status=AnalysisChunkResult.Status.QUEUED,
                error_category=exc.category, retry_count__gt=0,
            ).exists()
            if not exc.retryable or not checkpointed_retry:
                has_results = AnalysisChunkResult.objects.filter(
                    job_id=job_id, status=AnalysisChunkResult.Status.COMPLETED,
                ).exists()
                final_status = AnalysisJob.Status.PARTIALLY_COMPLETED if has_results else AnalysisJob.Status.FAILED
                AnalysisJob.objects.filter(pk=job_id).update(
                    status=final_status, completed_at=timezone.now(), processing_lease_until=None,
                    error_category=exc.category, error_message=exc.safe_message,
                    progress=_progress_for(job_id),
                )
                _settle_billing(job_id)
                return {'status': final_status}
            delay = _retry_delay(exc, job_id)
            next_attempt = timezone.now() + timedelta(seconds=delay)
            AnalysisJob.objects.filter(pk=job_id).update(
                status=AnalysisJob.Status.WAITING_FOR_QUOTA, progress=_progress_for(job_id),
                processing_lease_until=None, next_attempt_at=next_attempt,
                error_category=exc.category,
                error_message=(exc.safe_message if exc.category != 'provider_rate_limit'
                               else 'Waiting for available provider capacity; completed chunks are saved.'),
            )
            try:
                process_analysis_job.apply_async(args=(str(job_id),), countdown=delay, queue='ai')
            except Exception as schedule_error:
                logger.error('Could not schedule analysis resume (%s)', type(schedule_error).__name__, extra={
                    'analysis_job_id': str(job_id), 'error_category': 'resume_schedule_failed',
                })
                has_results = AnalysisChunkResult.objects.filter(job_id=job_id, status=AnalysisChunkResult.Status.COMPLETED).exists()
                final_status = AnalysisJob.Status.PARTIALLY_COMPLETED if has_results else AnalysisJob.Status.FAILED
                AnalysisJob.objects.filter(pk=job_id).update(
                    status=final_status, completed_at=timezone.now(), processing_lease_until=None,
                    error_category='queue_unavailable',
                    error_message='The analysis could not be scheduled to resume. Check the AI worker queue and retry later.',
                )
                _settle_billing(job_id)
                return {'status': final_status}
            return {'status': AnalysisJob.Status.WAITING_FOR_QUOTA, 'retry_after_seconds': delay}
        except Exception as exc:
            logger.error('Unexpected analysis processing failure (%s)', type(exc).__name__, extra={
                'analysis_job_id': str(job_id),
            })
            has_results = AnalysisChunkResult.objects.filter(job_id=job_id, status=AnalysisChunkResult.Status.COMPLETED).exists()
            final_status = AnalysisJob.Status.PARTIALLY_COMPLETED if has_results else AnalysisJob.Status.FAILED
            AnalysisJob.objects.filter(pk=job_id).update(
                status=final_status, completed_at=timezone.now(), processing_lease_until=None,
                error_category='processing_error',
                error_message='Analysis could not be completed. Please retry or contact support.',
            )
            _settle_billing(job_id)
            return {'status': final_status}
    except AnalysisJob.DoesNotExist:
        return {'status': 'missing'}
    finally:
        close_old_connections()
