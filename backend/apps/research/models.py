import uuid

from django.conf import settings
from django.db import models


class ResearchProject(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        ON_HOLD = 'on_hold', 'On hold'
        COMPLETED = 'completed', 'Completed'
        ARCHIVED = 'archived', 'Archived'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='research_projects')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    research_field = models.CharField(max_length=120, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)
        indexes = [models.Index(fields=('owner', 'status'))]

    def __str__(self):
        return self.title


class ResearchDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(ResearchProject, on_delete=models.CASCADE, related_name='documents')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='research_documents')
    original_filename = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at',)

    @property
    def current_version(self):
        return self.versions.all().first()

    def __str__(self):
        return self.original_filename


class DocumentVersion(models.Model):
    class ProcessingStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(ResearchDocument, on_delete=models.CASCADE, related_name='versions')
    revision_number = models.PositiveIntegerField()
    original_filename = models.CharField(max_length=255)
    file_extension = models.CharField(max_length=8)
    mime_type = models.CharField(max_length=120)
    file_size = models.PositiveBigIntegerField()
    storage_key = models.CharField(max_length=80, unique=True, editable=False)
    extraction_algorithm = models.CharField(max_length=40, default='academic-docx-v2')
    reprocessed_from = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE,
                                         related_name='extraction_revisions')
    processing_status = models.CharField(max_length=16, choices=ProcessingStatus.choices, default=ProcessingStatus.PENDING)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.CharField(max_length=240, blank=True)
    processing_attempt = models.PositiveIntegerField(default=0)
    extraction_metadata = models.JSONField(default=dict, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-revision_number',)
        constraints = [
            models.UniqueConstraint(fields=('document', 'revision_number'), name='research_doc_revision_unique'),
            models.UniqueConstraint(fields=('reprocessed_from', 'extraction_algorithm'),
                                    condition=models.Q(reprocessed_from__isnull=False),
                                    name='research_reprocess_algo_unique'),
        ]

    def __str__(self):
        return f'{self.document} v{self.revision_number}'

