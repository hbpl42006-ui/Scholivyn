import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone
from apps.billing.models import CreditReservation
from apps.billing.services.entitlements import mark_provider_started
from apps.billing.services.usage import settle_job

from .models import JournalRecommendationJob
from .services.providers.base import JournalProviderError
from .services.recommendations import build_recommendations

logger = logging.getLogger(__name__)


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True,
             name='publishing.process_journal_recommendation', queue='celery', max_retries=3)
def process_journal_recommendation(self, job_id):
    close_old_connections()
    try:
        job = JournalRecommendationJob.objects.select_related('profile__document_version').get(pk=job_id)
        if job.status in (JournalRecommendationJob.Status.COMPLETED, JournalRecommendationJob.Status.PARTIAL,
                          JournalRecommendationJob.Status.CANCELLED):
            if job.status == JournalRecommendationJob.Status.CANCELLED:
                settle_job('journal_recommendation', 'journal_job', job_id, success=False,
                           uncertain=bool(CreditReservation.objects.filter(reference_type='journal_job', reference_id=str(job_id), provider_started_at__isnull=False).exists()))
            return {'status':job.status}
        now = timezone.now()
        lease = now + timedelta(seconds=max(90, settings.JOURNAL_PROVIDER_TIMEOUT * 12))
        claim = (Q(status=JournalRecommendationJob.Status.QUEUED) |
                 (Q(status=JournalRecommendationJob.Status.PROCESSING) & (Q(lease_until__isnull=True) | Q(lease_until__lte=now))))
        if not JournalRecommendationJob.objects.filter(pk=job_id).filter(claim).update(
                status=JournalRecommendationJob.Status.PROCESSING, progress=10, lease_until=lease):
            return {'status':JournalRecommendationJob.objects.get(pk=job_id).status}
        try:
            self.apply_async(args=(str(job_id),), countdown=max(90, settings.JOURNAL_PROVIDER_TIMEOUT * 12), queue='celery')
        except Exception as exc:
            logger.warning('Publishing recovery watchdog scheduling failed type=%s', type(exc).__name__,
                           extra={'recommendation_job_id':str(job_id), 'error_category':'recovery_schedule_failed'})
        if not job.consent_to_external_metadata:
            JournalRecommendationJob.objects.filter(pk=job_id).update(status=JournalRecommendationJob.Status.FAILED,
                error_category='external_consent_required', lease_until=None, completed_at=timezone.now())
            return {'status':JournalRecommendationJob.Status.FAILED}
        reservation = CreditReservation.objects.filter(reference_type='journal_job', reference_id=str(job_id)).first()
        mark_provider_started(reservation)
        count = build_recommendations(job)
        job.refresh_from_db(fields=('status',))
        if job.status == JournalRecommendationJob.Status.CANCELLED:
            return {'status':job.status}
        final = JournalRecommendationJob.Status.COMPLETED if count else JournalRecommendationJob.Status.PARTIAL
        JournalRecommendationJob.objects.filter(pk=job_id).update(status=final, progress=100, result_count=count,
            error_category='' if count else 'no_provider_results', lease_until=None, completed_at=timezone.now())
        settle_job('journal_recommendation', 'journal_job', job_id, success=bool(count), units=1,
                   uncertain=not bool(count))
        return {'status':final, 'result_count':count}
    except JournalProviderError as exc:
        job = JournalRecommendationJob.objects.filter(pk=job_id).first()
        if not job: raise
        if exc.retryable and self.request.retries < settings.JOURNAL_RETRY_LIMIT:
            delay = exc.retry_after or min(900, 15 * (2 ** self.request.retries))
            JournalRecommendationJob.objects.filter(pk=job_id).update(status=JournalRecommendationJob.Status.QUEUED,
                error_category=exc.category, lease_until=None)
            raise self.retry(exc=exc, countdown=delay)
        partial = bool(job.providers_completed or job.journal_snapshots.exists())
        final = JournalRecommendationJob.Status.PARTIAL if partial else JournalRecommendationJob.Status.FAILED
        JournalRecommendationJob.objects.filter(pk=job_id).update(status=final, error_category=exc.category,
            lease_until=None, completed_at=timezone.now())
        settle_job('journal_recommendation', 'journal_job', job_id, success=partial, units=1,
                   uncertain=not partial)
        return {'status':final}
    except Exception:
        JournalRecommendationJob.objects.filter(pk=job_id).exclude(status=JournalRecommendationJob.Status.CANCELLED).update(
            status=JournalRecommendationJob.Status.FAILED, error_category='recommendation_processing_failed',
            lease_until=None, completed_at=timezone.now())
        settle_job('journal_recommendation', 'journal_job', job_id, success=False, uncertain=True)
        raise
    finally:
        close_old_connections()
