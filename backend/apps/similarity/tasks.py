from celery import shared_task
from datetime import timedelta
import logging
from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone
from apps.billing.services.usage import settle_job

from apps.research.models import DocumentVersion
from .models import SimilarityComparison, SimilarityJob, SimilarityMatch
from .services.matching import compare_documents, paragraphs_from_metadata, tokens
from .services.sources import OwnedWorkspaceVersionProvider

logger = logging.getLogger(__name__)

@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True,
             name='similarity.process_similarity_job', queue='celery')
def process_similarity_job(self, job_id):
    close_old_connections()
    try:
        job = SimilarityJob.objects.select_related('source_version').get(pk=job_id)
        if job.status in (SimilarityJob.Status.CANCELLED, SimilarityJob.Status.COMPLETED):
            return {'status': job.status}
        now = timezone.now()
        claimable = Q(status__in=(SimilarityJob.Status.QUEUED, SimilarityJob.Status.FAILED)) | (
            Q(status=SimilarityJob.Status.PROCESSING) & (Q(lease_until__isnull=True) | Q(lease_until__lte=now)))
        lease_seconds = settings.SIMILARITY_WORKER_LEASE_SECONDS
        if not SimilarityJob.objects.filter(pk=job_id).filter(claimable).update(
                status=SimilarityJob.Status.PROCESSING, error_message='', lease_until=now + timedelta(seconds=lease_seconds)):
            existing = SimilarityJob.objects.get(pk=job_id)
            if existing.status == SimilarityJob.Status.PROCESSING and existing.lease_until:
                _schedule_recovery(self, job_id, max(5, int((existing.lease_until - now).total_seconds()) + 1))
            return {'status': existing.status}
        _schedule_recovery(self, job_id, lease_seconds + 1)
        source_snapshot, selected_targets = OwnedWorkspaceVersionProvider().load_selected_versions(job)
        source = source_snapshot.version
        target_by_id = {item.version.pk: item for item in selected_targets}
        comparisons = list(job.comparisons.select_related('target_version__document__project').prefetch_related('matches'))
        total_words = 0
        total_matched = 0
        for index, comparison in enumerate(comparisons):
            if SimilarityJob.objects.filter(pk=job_id, status=SimilarityJob.Status.CANCELLED).exists():
                settle_job('similarity_comparison', 'similarity_job', job_id, success=False)
                return {'status': SimilarityJob.Status.CANCELLED}
            if comparison.status != 'completed':
                target_snapshot = target_by_id.get(comparison.target_version_id)
                if target_snapshot is None:
                    raise ValueError('A selected target version is outside this job scope.')
                target = target_snapshot.version
                if source.processing_status != DocumentVersion.ProcessingStatus.COMPLETED or target.processing_status != DocumentVersion.ProcessingStatus.COMPLETED:
                    raise ValueError('Both selected manuscript versions must have completed extraction.')
                result = compare_documents(source_snapshot.extraction_metadata, target_snapshot.extraction_metadata,
                                           min_words=job.min_passage_words, near_threshold=job.near_threshold,
                                           shingle_size=job.shingle_size)
                with transaction.atomic():
                    if SimilarityJob.objects.filter(pk=job_id, status=SimilarityJob.Status.CANCELLED).exists():
                        settle_job('similarity_comparison', 'similarity_job', job_id, success=False)
                        return {'status': SimilarityJob.Status.CANCELLED}
                    comparison.matches.all().delete()
                    SimilarityMatch.objects.bulk_create([
                        SimilarityMatch(comparison=comparison, match_type=row['match_type'],
                            source_section_key=row['source_section_key'], source_section_title=row['source_section_title'][:255],
                            source_paragraph_id=row['source_paragraph_id'][:100], source_paragraph_index=row['source_paragraph_index'],
                            source_start=row['source_start'], source_end=row['source_end'],
                            target_section_key=row['target_section_key'], target_section_title=row['target_section_title'][:255],
                            target_paragraph_id=row['target_paragraph_id'][:100], target_paragraph_index=row['target_paragraph_index'],
                            target_start=row['target_start'], target_end=row['target_end'], similarity=row['similarity'],
                            source_word_count=row['source_word_count'], citation_label=row['citation_label'])
                        for row in result['matches']
                    ])
                    comparison.status = 'completed'
                    comparison.exact_match_count = result['exact_match_count']
                    comparison.near_match_count = result['near_match_count']
                    comparison.matched_source_words = result['matched_source_words']
                    comparison.save(update_fields=('status', 'exact_match_count', 'near_match_count', 'matched_source_words'))
            total_words = max(total_words, sum(len(tokens(item.text)) for item in paragraphs_from_metadata(source_snapshot.extraction_metadata)))
            SimilarityJob.objects.filter(pk=job_id, status=SimilarityJob.Status.PROCESSING).update(
                progress=min(99, int((index + 1) * 100 / max(1, len(comparisons)))), completed_targets=index + 1,
                lease_until=timezone.now() + timedelta(seconds=lease_seconds))
        # Count the union of matching source-token spans across all target
        # comparisons so overlapping sources do not inflate coverage.
        intervals = {}
        for match in SimilarityMatch.objects.filter(comparison__job_id=job_id):
            key = (match.source_section_key, match.source_paragraph_id, match.source_paragraph_index)
            intervals.setdefault(key, []).append((match.source_start, match.source_end))
        source_paragraphs = {(p.section_key, p.paragraph_id, p.paragraph_index): p
                             for p in paragraphs_from_metadata(source_snapshot.extraction_metadata)}
        for key, spans in intervals.items():
            paragraph = source_paragraphs.get(key)
            if paragraph is None:
                continue
            united = []
            for start, end in sorted(spans):
                if united and start <= united[-1][1]:
                    united[-1] = (united[-1][0], max(united[-1][1], end))
                else:
                    united.append((start, end))
            paragraph_tokens = tokens(paragraph.text)
            total_matched += sum(1 for start, end in united for token in paragraph_tokens if start <= token.start and token.end <= end)
        denominator = max(1, total_words)
        # Union by selected comparison is capped at source denominator; this is
        # explicit source coverage across the selected comparison set.
        total_matched = min(total_words, total_matched)
        SimilarityJob.objects.filter(pk=job_id, status=SimilarityJob.Status.PROCESSING).update(
            status=SimilarityJob.Status.COMPLETED, progress=100, completed_targets=len(comparisons),
            exact_match_count=sum(item.exact_match_count for item in comparisons),
            near_match_count=sum(item.near_match_count for item in comparisons),
            source_word_count=total_words, matched_source_words=total_matched,
            matched_percentage=round(100 * total_matched / denominator, 2) if total_words else 0,
            completed_at=timezone.now())
        SimilarityJob.objects.filter(pk=job_id).update(lease_until=None)
        settle_job('similarity_comparison', 'similarity_job', job_id, success=True,
                   units=len(comparisons))
        return {'status': SimilarityJob.Status.COMPLETED}
    except Exception:
        settle_job('similarity_comparison', 'similarity_job', job_id, success=False)
        SimilarityJob.objects.filter(pk=job_id).exclude(status=SimilarityJob.Status.CANCELLED).update(
            status=SimilarityJob.Status.FAILED, error_message='Similarity processing failed. Retry the comparison or contact support.',
            completed_at=timezone.now(), lease_until=None)
        raise
    finally:
        close_old_connections()


def _schedule_recovery(task, job_id, delay):
    delivery = getattr(task.request, 'delivery_info', None) or {}
    if delivery and not settings.CELERY_TASK_ALWAYS_EAGER:
        try:
            task.apply_async(args=(str(job_id),), countdown=max(1, delay), queue='celery')
        except Exception as exc:
            logger.warning('Similarity recovery watchdog could not be scheduled (%s).', type(exc).__name__,
                           extra={'similarity_job_id': str(job_id), 'error_category': 'recovery_schedule_failed'})
