from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from .models import DocumentVersion
from .services import extract_document


@shared_task(bind=True, max_retries=2, default_retry_delay=5, name='research.process_document_version')
def process_document_version(self, version_id):
    close_old_connections()
    attempt = None
    try:
        # Atomic claim fences duplicate delivery. The monotonically increasing
        # attempt also prevents a late/stale worker from overwriting a retry.
        with transaction.atomic():
            claimed = DocumentVersion.objects.filter(
                pk=version_id, processing_status=DocumentVersion.ProcessingStatus.PENDING,
            ).update(processing_status=DocumentVersion.ProcessingStatus.PROCESSING,
                     processing_started_at=timezone.now(), processing_error='',
                     processing_attempt=F('processing_attempt') + 1)
            version = DocumentVersion.objects.get(pk=version_id)
            if not claimed:
                return {'status': version.processing_status, 'duplicate_delivery': True}
            attempt = version.processing_attempt

        result = extract_document(Path(settings.PRIVATE_DOCUMENT_ROOT) / version.storage_key, version.file_extension)
        updated = DocumentVersion.objects.filter(pk=version_id,
            processing_status=DocumentVersion.ProcessingStatus.PROCESSING,
            processing_attempt=attempt).update(extraction_metadata=result,
                processing_status=DocumentVersion.ProcessingStatus.COMPLETED,
                processing_started_at=None, processing_error='')
        if not updated:
            return {'status': DocumentVersion.objects.get(pk=version_id).processing_status, 'stale_attempt': True}
        return {'status': DocumentVersion.ProcessingStatus.COMPLETED}
    except DocumentVersion.DoesNotExist:
        return {'status': 'missing'}
    except Exception as exc:
        try:
            version = DocumentVersion.objects.get(pk=version_id)
        except DocumentVersion.DoesNotExist:
            return {'status': 'missing'}
        if attempt is None:
            return {'status': version.processing_status}

        claim = DocumentVersion.objects.filter(pk=version_id,
            processing_status=DocumentVersion.ProcessingStatus.PROCESSING,
            processing_attempt=attempt)
        if self.request.retries >= self.max_retries:
            updated = claim.update(processing_status=DocumentVersion.ProcessingStatus.FAILED,
                extraction_metadata={'error': 'Document extraction failed. Please upload a valid file or try again.'},
                processing_started_at=None,
                processing_error='Document extraction failed. Please upload a valid file or retry extraction.')
            if not updated:
                return {'status': DocumentVersion.objects.get(pk=version_id).processing_status, 'stale_attempt': True}
            return {'status': DocumentVersion.ProcessingStatus.FAILED}

        updated = claim.update(processing_status=DocumentVersion.ProcessingStatus.PENDING,
            processing_started_at=None, processing_error='Extraction failed temporarily and will be retried.')
        if not updated:
            return {'status': DocumentVersion.objects.get(pk=version_id).processing_status, 'stale_attempt': True}
        countdown = 0 if settings.CELERY_TASK_ALWAYS_EAGER else self.default_retry_delay
        raise self.retry(exc=exc, countdown=countdown)
    finally:
        close_old_connections()
