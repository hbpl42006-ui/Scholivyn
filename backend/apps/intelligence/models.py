import uuid

from django.conf import settings
from django.db import models

from apps.research.models import DocumentVersion, ResearchDocument, ResearchProject


class AnalysisJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        WAITING_FOR_QUOTA = 'waiting_for_quota', 'Waiting for provider capacity'
        COMPLETED = 'completed', 'Completed'
        PARTIALLY_COMPLETED = 'partially_completed', 'Partially completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='analysis_jobs')
    project = models.ForeignKey(ResearchProject, on_delete=models.PROTECT, related_name='analysis_jobs')
    document = models.ForeignKey(ResearchDocument, on_delete=models.PROTECT, related_name='analysis_jobs')
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='analysis_jobs')
    analysis_type = models.CharField(max_length=40, default='academic_review')
    reviewer_profile = models.CharField(max_length=40, default='general')
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.QUEUED)
    progress = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    processing_lease_until = models.DateTimeField(null=True, blank=True)
    chunk_token_limit = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_category = models.CharField(max_length=40, blank=True)
    error_message = models.CharField(max_length=240, blank=True)
    provider = models.CharField(max_length=40)
    model_identifier = models.CharField(max_length=120)
    prompt_version = models.CharField(max_length=32, default='academic-review-v2')
    external_processing_consent = models.BooleanField(default=False)
    client_request_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=('owner', 'status')), models.Index(fields=('document_version', 'status'))]
        constraints = [models.UniqueConstraint(fields=('owner', 'client_request_id'), name='ia_job_owner_req_uq')]

    def __str__(self):
        return f'{self.analysis_type} ({self.status})'


class AnalysisSectionResult(models.Model):
    class ProcessingStatus(models.TextChoices):
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name='section_results')
    section_key = models.CharField(max_length=120)
    section_title = models.CharField(max_length=180)
    section_category = models.CharField(max_length=40, db_index=True)
    review_summary = models.TextField(blank=True)
    strengths = models.JSONField(default=list, blank=True)
    weaknesses = models.JSONField(default=list, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    processing_status = models.CharField(max_length=16, choices=ProcessingStatus.choices, default=ProcessingStatus.PROCESSING)
    completed_chunks = models.PositiveIntegerField(default=0)
    failed_chunks = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('id',)
        constraints = [models.UniqueConstraint(fields=('job', 'section_key'), name='ia_job_section_key_uq')]

    def __str__(self):
        return f'{self.section_title}: {self.processing_status}'


class AnalysisIssue(models.Model):
    class Severity(models.TextChoices):
        CRITICAL = 'critical', 'Critical'
        HIGH = 'high', 'High'
        MEDIUM = 'medium', 'Medium'
        LOW = 'low', 'Low'
        INFORMATIONAL = 'informational', 'Informational'

    class Resolution(models.TextChoices):
        OPEN = 'open', 'Open'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        RESOLVED = 'resolved', 'Resolved'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name='issues')
    section = models.ForeignKey(AnalysisSectionResult, on_delete=models.CASCADE, related_name='issues')
    fingerprint = models.CharField(max_length=64)
    category = models.CharField(max_length=60, db_index=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, db_index=True)
    title = models.CharField(max_length=220)
    explanation = models.TextField()
    evidence_snippet = models.TextField()
    source_paragraph_index = models.PositiveIntegerField(null=True, blank=True)
    suggested_improvement = models.TextField(blank=True)
    resolution_status = models.CharField(max_length=16, choices=Resolution.choices, default=Resolution.OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-severity', 'created_at')
        constraints = [models.UniqueConstraint(fields=('job', 'fingerprint'), name='ia_job_issue_fp_uq')]
        indexes = [models.Index(fields=('job', 'severity', 'resolution_status'), name='ia_issue_filter_idx')]

    def __str__(self):
        return self.title


class WritingSuggestion(models.Model):
    class Status(models.TextChoices):
        PROPOSED = 'proposed', 'Proposed'
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.OneToOneField(AnalysisIssue, on_delete=models.CASCADE, related_name='writing_suggestion')
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='writing_suggestions')
    original_text = models.TextField()
    suggested_text = models.TextField()
    explanation = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    source_paragraph_index = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Suggestion for {self.issue_id}'


class AnalysisChunkResult(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        SUPERSEDED = 'superseded', 'Superseded by smaller chunks'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name='chunks')
    section = models.ForeignKey(AnalysisSectionResult, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    retry_count = models.PositiveSmallIntegerField(default=0)
    source_ranges = models.JSONField(default=list, blank=True)
    parent_chunk = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='child_chunks')
    structured_result = models.JSONField(default=dict, blank=True)
    error_category = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('section_id', 'chunk_index')
        constraints = [models.UniqueConstraint(fields=('section', 'chunk_index'), name='ia_section_chunk_uq')]

    def __str__(self):
        return f'{self.section.section_title} chunk {self.chunk_index}'


class AIUsageRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_usage_records')
    job = models.ForeignKey(AnalysisJob, on_delete=models.CASCADE, related_name='usage_records')
    provider = models.CharField(max_length=40)
    model_identifier = models.CharField(max_length=120)
    request_key = models.CharField(max_length=160)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    reasoning_tokens = models.PositiveIntegerField(null=True, blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    processing_duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at',)
        constraints = [models.UniqueConstraint(fields=('job', 'request_key'), name='ia_job_usage_key_uq')]

    def __str__(self):
        return f'{self.provider}/{self.model_identifier} usage'
