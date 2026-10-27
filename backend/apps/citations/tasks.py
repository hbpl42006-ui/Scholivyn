import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone
from apps.billing.services.usage import settle_job

from .models import (BibliographicReference, CitationAnalysisJob, CitationFinding,
                     CitationMatch, ExtractedCitation, MetadataVerification)
from .services.extraction import extract_document_citations
from .services.matching import reconcile
from .services.metadata import MetadataProviderError, PROVIDERS, check_reference
from .services.style_validation import validate_style

logger = logging.getLogger(__name__)


def _queue(task, job_id, *, countdown=None):
    try:
        task.apply_async(args=(str(job_id),), countdown=countdown, queue='celery')
        return True
    except Exception as exc:
        logger.warning('Citation task enqueue failed error_type=%s', type(exc).__name__,
                       extra={'citation_job_id': str(job_id), 'error_category': 'queue_unavailable'})
        return False


def _schedule_metadata(job_id, countdown):
    if _queue(verify_citation_metadata, job_id, countdown=countdown):
        return True
    CitationAnalysisJob.objects.filter(pk=job_id).update(metadata_status='failed')
    return False


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True, name='citations.process_citation_analysis', queue='celery')
def process_citation_analysis(self, job_id):
    close_old_connections()
    try:
        job = CitationAnalysisJob.objects.select_related('document_version').get(pk=job_id)
        if job.status in (CitationAnalysisJob.Status.CANCELLED, CitationAnalysisJob.Status.COMPLETED):
            if job.status == CitationAnalysisJob.Status.CANCELLED:
                settle_job('citation_analysis', 'citation_job', job_id, success=False)
            return {'status': job.status}
        now = timezone.now()
        lease = now + timedelta(seconds=max(90, settings.CITATION_PROVIDER_TIMEOUT * 10))
        can_claim = Q(status__in=(CitationAnalysisJob.Status.QUEUED, CitationAnalysisJob.Status.FAILED)) | (
            Q(status=CitationAnalysisJob.Status.PROCESSING) & (Q(lease_until__isnull=True) | Q(lease_until__lte=now)))
        claimed = CitationAnalysisJob.objects.filter(pk=job_id).filter(can_claim).update(
            status=CitationAnalysisJob.Status.PROCESSING, progress=5, error_category='', error_message='', lease_until=lease)
        if not claimed:
            current = CitationAnalysisJob.objects.get(pk=job_id)
            return {'status': current.status}
        try:
            self.apply_async(args=(str(job_id),), countdown=max(90, settings.CITATION_PROVIDER_TIMEOUT * 10), queue='celery')
        except Exception as exc:
            logger.warning('Citation recovery watchdog scheduling failed type=%s', type(exc).__name__,
                           extra={'citation_job_id': str(job_id), 'error_category': 'recovery_schedule_failed'})
        version = job.document_version
        if version.processing_status != 'completed':
            raise ValueError('document_extraction_incomplete')
        extracted = extract_document_citations(version.extraction_metadata or {}, settings.CITATION_MAX_REFERENCES)
        if extracted['reference_limit_reached']:
            logger.info('Citation reference parse limit reached job=%s', job_id)
        result = reconcile(extracted['citations'], extracted['references'], job.citation_style)
        style_findings = validate_style(extracted['citations'], result['detected_style'])
        all_findings = result['findings'] + style_findings
        if result['detected_style'] == 'auto':
            all_findings.append({'citation': None, 'reference': None, 'code': 'unsupported_citation_style', 'severity': 'warning',
                                 'explanation': 'Automatic detection did not identify IEEE or APA 7 confidently; no full style-compliance claim is made.'})
        with transaction.atomic():
            locked = CitationAnalysisJob.objects.select_for_update().get(pk=job_id)
            if locked.status == CitationAnalysisJob.Status.CANCELLED:
                settle_job('citation_analysis', 'citation_job', job_id, success=False)
                return {'status': locked.status}
            # One transaction replaces only this job's derived rows. Duplicate
            # Celery delivery after completion exits above; crashes roll back.
            locked.citations.all().delete()
            locked.references.all().delete()
            locked.matches.all().delete()
            locked.findings.all().delete()
            citation_map, reference_map = {}, {}
            for row in extracted['citations']:
                obj = ExtractedCitation.objects.create(job=locked, **{key: row[key] for key in (
                    'style','raw_text','numeric_values','author_keys','years','section_key','section_title','paragraph_id',
                    'paragraph_index','start_offset','end_offset')})
                citation_map[id(row)] = obj
            for row in extracted['references']:
                obj = BibliographicReference.objects.create(job=locked, **{key: row[key] for key in (
                    'raw_text','reference_number','authors','author_key','title','publication','year','doi','doi_normalized',
                    'urls','confidence','section_key','section_title','paragraph_id','paragraph_index','start_offset','end_offset')})
                reference_map[id(row)] = obj
            for row in result['matches']:
                CitationMatch.objects.create(job=locked, citation=citation_map.get(id(row['citation'])) if row['citation'] else None,
                    reference=reference_map.get(id(row['reference'])) if row['reference'] else None,
                    status=row['status'], issue_code=row['issue_code'], explanation=row['explanation'])
            for row in all_findings:
                citation = row.get('citation')
                reference = row.get('reference')
                CitationFinding.objects.create(job=locked,
                    citation=citation_map.get(id(citation)) if citation else None,
                    reference=reference_map.get(id(reference)) if reference else None,
                    code=row['code'], severity=row['severity'], explanation=row['explanation'],
                    source_section_key=row.get('source_section_key', citation.get('section_key', '') if citation else reference.get('section_key', '') if reference else ''),
                    source_section_title=row.get('source_section_title', citation.get('section_title', '') if citation else reference.get('section_title', '') if reference else ''),
                    source_paragraph_id=row.get('source_paragraph_id', citation.get('paragraph_id', '') if citation else reference.get('paragraph_id', '') if reference else ''),
                    source_paragraph_index=row.get('source_paragraph_index', citation.get('paragraph_index') if citation else reference.get('paragraph_index') if reference else None),
                    source_start=row.get('source_start', citation.get('start_offset') if citation else reference.get('start_offset') if reference else None),
                    source_end=row.get('source_end', citation.get('end_offset') if citation else reference.get('end_offset') if reference else None))
            statuses = [row['status'] for row in result['matches']]
            locked.status = CitationAnalysisJob.Status.COMPLETED
            locked.progress = 100
            locked.citation_count = len(extracted['citations'])
            locked.reference_count = len(extracted['references'])
            locked.matched_count = statuses.count('matched')
            locked.unmatched_count = statuses.count('unmatched')
            locked.ambiguous_count = statuses.count('ambiguous')
            locked.incomplete_count = statuses.count('incomplete')
            locked.completed_at = timezone.now()
            locked.lease_until = None
            locked.metadata_status = 'queued' if locked.metadata_consent else 'not_checked'
            locked.save()
            if locked.metadata_consent:
                transaction.on_commit(lambda: _enqueue(verify_citation_metadata, locked.pk))
        settle_job('citation_analysis', 'citation_job', job_id, success=True, units=1)
        return {'status': CitationAnalysisJob.Status.COMPLETED}
    except Exception as exc:
        settle_job('citation_analysis', 'citation_job', job_id, success=False)
        category = 'document_extraction_incomplete' if str(exc) == 'document_extraction_incomplete' else 'citation_processing_failed'
        CitationAnalysisJob.objects.filter(pk=job_id).exclude(status=CitationAnalysisJob.Status.CANCELLED).update(
            status=CitationAnalysisJob.Status.FAILED, error_category=category,
            error_message='Citation analysis could not be completed. Confirm extraction is complete and retry.',
            lease_until=None, completed_at=timezone.now())
        raise
    finally:
        close_old_connections()


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True, name='citations.verify_citation_metadata', queue='celery', max_retries=3)
def verify_citation_metadata(self, job_id):
    close_old_connections()
    try:
        job = CitationAnalysisJob.objects.get(pk=job_id)
        if not job.metadata_consent or job.status != CitationAnalysisJob.Status.COMPLETED:
            return {'status': 'not_checked'}
        if not settings.CITATION_METADATA_ENABLED:
            CitationAnalysisJob.objects.filter(pk=job_id).update(metadata_status='disabled')
            return {'status': 'disabled'}
        references = list(job.references.order_by('id')[:settings.CITATION_MAX_METADATA_LOOKUPS])
        CitationAnalysisJob.objects.filter(pk=job_id).update(metadata_status='processing')
        for reference in references:
            if not (reference.doi_normalized or reference.title):
                continue
            for provider in PROVIDERS:
                check, _ = MetadataVerification.objects.get_or_create(reference=reference, provider=provider.name)
                if check.status != 'not_checked':
                    continue
                try:
                    result = check_reference(reference, provider)
                except MetadataProviderError as exc:
                    check.status = 'not_checked'
                    check.error_category = exc.category
                    check.verified_at = timezone.now()
                    check.attempt_count += 1
                    if exc.retryable and check.attempt_count < 4:
                        check.save(update_fields=('status', 'error_category', 'attempt_count', 'verified_at'))
                        delay = exc.retry_after or min(900, 30 * (2 ** (check.attempt_count - 1)))
                        _schedule_metadata(job_id, delay)
                        return {'status': 'waiting_for_provider', 'provider': provider.name}
                    check.status = 'unavailable' if exc.retryable or exc.category != 'not_found' else 'not_found'
                    check.save(update_fields=('status', 'error_category', 'attempt_count', 'verified_at'))
                    # One bounded lookup per task delivery. Requeueing the
                    # cursor allows the other provider/references to proceed
                    # without sleeping or discarding completed checks.
                    _schedule_metadata(job_id, 1)
                    return {'status': 'provider_unavailable' if exc.retryable else 'continued'}
                check.status = result['status']; check.confidence = result['confidence']
                check.metadata = result['metadata']; check.source_url = result['source_url']
                check.error_category = result['error_category']; check.verified_at = timezone.now()
                check.save()
                # A short scheduled continuation respects both providers'
                # public API etiquette and avoids occupying the worker.
                _schedule_metadata(job_id, 1)
                return {'status': 'processing'}
        failed = MetadataVerification.objects.filter(reference__job_id=job_id, status='unavailable').exists()
        CitationAnalysisJob.objects.filter(pk=job_id).update(metadata_status='partial' if failed else 'completed')
        return {'status': 'completed'}
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            CitationAnalysisJob.objects.filter(pk=job_id).update(metadata_status='failed')
        raise
    finally:
        close_old_connections()
