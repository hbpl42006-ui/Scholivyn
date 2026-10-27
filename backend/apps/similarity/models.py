import uuid

from django.conf import settings
from django.db import models

from apps.research.models import DocumentVersion


class SimilarityJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='similarity_jobs')
    source_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='similarity_source_jobs')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    client_request_id = models.UUIDField()
    min_passage_words = models.PositiveSmallIntegerField()
    near_threshold = models.FloatField()
    shingle_size = models.PositiveSmallIntegerField()
    progress = models.PositiveSmallIntegerField(default=0)
    total_targets = models.PositiveSmallIntegerField(default=0)
    completed_targets = models.PositiveSmallIntegerField(default=0)
    exact_match_count = models.PositiveIntegerField(default=0)
    near_match_count = models.PositiveIntegerField(default=0)
    matched_source_words = models.PositiveIntegerField(default=0)
    source_word_count = models.PositiveIntegerField(default=0)
    matched_percentage = models.FloatField(default=0)
    error_message = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [models.UniqueConstraint(fields=('owner', 'client_request_id'), name='similarity_owner_request_unique')]
        indexes = [models.Index(fields=('owner', 'status')), models.Index(fields=('status', 'created_at'))]


class SimilarityComparison(models.Model):
    job = models.ForeignKey(SimilarityJob, on_delete=models.CASCADE, related_name='comparisons')
    target_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='similarity_target_comparisons')
    status = models.CharField(max_length=16, default='pending')
    exact_match_count = models.PositiveIntegerField(default=0)
    near_match_count = models.PositiveIntegerField(default=0)
    matched_source_words = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('job', 'target_version'), name='similarity_job_target_unique')]


class SimilarityMatch(models.Model):
    class MatchType(models.TextChoices):
        EXACT = 'exact', 'Exact'
        NEAR = 'near_duplicate', 'Near duplicate'

    comparison = models.ForeignKey(SimilarityComparison, on_delete=models.CASCADE, related_name='matches')
    match_type = models.CharField(max_length=20, choices=MatchType.choices)
    source_section_key = models.CharField(max_length=100, blank=True)
    source_section_title = models.CharField(max_length=255, blank=True)
    source_paragraph_id = models.CharField(max_length=100, blank=True)
    source_paragraph_index = models.PositiveIntegerField()
    source_start = models.PositiveIntegerField()
    source_end = models.PositiveIntegerField()
    target_section_key = models.CharField(max_length=100, blank=True)
    target_section_title = models.CharField(max_length=255, blank=True)
    target_paragraph_id = models.CharField(max_length=100, blank=True)
    target_paragraph_index = models.PositiveIntegerField()
    target_start = models.PositiveIntegerField()
    target_end = models.PositiveIntegerField()
    similarity = models.FloatField()
    source_word_count = models.PositiveIntegerField()
    citation_label = models.CharField(max_length=32)

    class Meta:
        ordering = ('source_section_title', 'source_paragraph_index', 'source_start', 'target_paragraph_index')
        indexes = [models.Index(fields=('comparison', 'match_type'))]
