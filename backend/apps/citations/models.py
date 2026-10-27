import uuid

from django.conf import settings
from django.db import models

from apps.research.models import DocumentVersion


class CitationAnalysisJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    class Style(models.TextChoices):
        AUTO = 'auto', 'Detect automatically'
        IEEE = 'ieee', 'IEEE'
        APA7 = 'apa7', 'APA 7'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='citation_analysis_jobs')
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='citation_analysis_jobs')
    client_request_id = models.UUIDField()
    citation_style = models.CharField(max_length=12, choices=Style.choices, default=Style.AUTO)
    metadata_consent = models.BooleanField(default=False)
    metadata_status = models.CharField(max_length=16, default='not_checked')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    progress = models.PositiveSmallIntegerField(default=0)
    citation_count = models.PositiveIntegerField(default=0)
    reference_count = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    unmatched_count = models.PositiveIntegerField(default=0)
    ambiguous_count = models.PositiveIntegerField(default=0)
    incomplete_count = models.PositiveIntegerField(default=0)
    error_category = models.CharField(max_length=40, blank=True)
    error_message = models.CharField(max_length=240, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [models.UniqueConstraint(fields=('owner', 'client_request_id'), name='citation_owner_request_unique')]
        indexes = [models.Index(fields=('owner', 'status')), models.Index(fields=('status', 'created_at'))]


class ExtractedCitation(models.Model):
    class Style(models.TextChoices):
        IEEE = 'ieee', 'IEEE numeric'
        APA7 = 'apa7', 'APA author-year'
        UNSUPPORTED = 'unsupported', 'Unsupported'

    job = models.ForeignKey(CitationAnalysisJob, on_delete=models.CASCADE, related_name='citations')
    style = models.CharField(max_length=12, choices=Style.choices)
    raw_text = models.CharField(max_length=500)
    numeric_values = models.JSONField(default=list, blank=True)
    author_keys = models.JSONField(default=list, blank=True)
    years = models.JSONField(default=list, blank=True)
    section_key = models.CharField(max_length=100, blank=True)
    section_title = models.CharField(max_length=255, blank=True)
    paragraph_id = models.CharField(max_length=100, blank=True)
    paragraph_index = models.PositiveIntegerField()
    start_offset = models.PositiveIntegerField()
    end_offset = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('section_title', 'paragraph_index', 'start_offset')
        indexes = [models.Index(fields=('job', 'style')), models.Index(fields=('job', 'paragraph_index'))]


class BibliographicReference(models.Model):
    job = models.ForeignKey(CitationAnalysisJob, on_delete=models.CASCADE, related_name='references')
    raw_text = models.TextField()
    reference_number = models.PositiveIntegerField(null=True, blank=True)
    authors = models.JSONField(default=list, blank=True)
    author_key = models.CharField(max_length=120, blank=True)
    title = models.CharField(max_length=1000, blank=True)
    publication = models.CharField(max_length=500, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    doi = models.CharField(max_length=500, blank=True)
    doi_normalized = models.CharField(max_length=500, blank=True)
    urls = models.JSONField(default=list, blank=True)
    confidence = models.CharField(max_length=16, default='heuristic')
    section_key = models.CharField(max_length=100, blank=True)
    section_title = models.CharField(max_length=255, blank=True)
    paragraph_id = models.CharField(max_length=100, blank=True)
    paragraph_index = models.PositiveIntegerField()
    start_offset = models.PositiveIntegerField(default=0)
    end_offset = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('reference_number', 'paragraph_index')
        indexes = [models.Index(fields=('job', 'reference_number')), models.Index(fields=('job', 'doi_normalized'))]


class CitationMatch(models.Model):
    class Status(models.TextChoices):
        MATCHED = 'matched', 'Matched'
        UNMATCHED = 'unmatched', 'Unmatched'
        AMBIGUOUS = 'ambiguous', 'Ambiguous'
        INCOMPLETE = 'incomplete', 'Incomplete'
        NOT_CHECKED = 'not_checked', 'Not checked'

    job = models.ForeignKey(CitationAnalysisJob, on_delete=models.CASCADE, related_name='matches')
    citation = models.ForeignKey(ExtractedCitation, null=True, blank=True, on_delete=models.CASCADE, related_name='matches')
    reference = models.ForeignKey(BibliographicReference, null=True, blank=True, on_delete=models.CASCADE, related_name='matches')
    status = models.CharField(max_length=16, choices=Status.choices)
    issue_code = models.CharField(max_length=40, blank=True)
    explanation = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('status', 'id')
        indexes = [models.Index(fields=('job', 'status')), models.Index(fields=('job', 'issue_code'))]


class CitationFinding(models.Model):
    class Severity(models.TextChoices):
        ERROR = 'definite_error', 'Definite structural issue'
        WARNING = 'warning', 'Review warning'

    job = models.ForeignKey(CitationAnalysisJob, on_delete=models.CASCADE, related_name='findings')
    citation = models.ForeignKey(ExtractedCitation, null=True, blank=True, on_delete=models.CASCADE, related_name='findings')
    reference = models.ForeignKey(BibliographicReference, null=True, blank=True, on_delete=models.CASCADE, related_name='findings')
    code = models.CharField(max_length=48)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    explanation = models.CharField(max_length=500)
    source_section_key = models.CharField(max_length=100, blank=True)
    source_section_title = models.CharField(max_length=255, blank=True)
    source_paragraph_id = models.CharField(max_length=100, blank=True)
    source_paragraph_index = models.PositiveIntegerField(null=True, blank=True)
    source_start = models.PositiveIntegerField(null=True, blank=True)
    source_end = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('severity', 'code', 'id')
        indexes = [models.Index(fields=('job', 'code')), models.Index(fields=('job', 'severity'))]


class MetadataVerification(models.Model):
    class Provider(models.TextChoices):
        CROSSREF = 'crossref', 'Crossref'
        OPENALEX = 'openalex', 'OpenAlex'

    reference = models.ForeignKey(BibliographicReference, on_delete=models.CASCADE, related_name='metadata_checks')
    provider = models.CharField(max_length=12, choices=Provider.choices)
    status = models.CharField(max_length=16, default='not_checked')
    confidence = models.FloatField(null=True, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    error_category = models.CharField(max_length=40, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('reference', 'provider'), name='citation_metadata_provider_unique')]


class CitationReviewDecision(models.Model):
    class Decision(models.TextChoices):
        ACCEPTED = 'accepted', 'Accepted'
        REJECTED = 'rejected', 'Rejected'
        NEEDS_REVIEW = 'needs_review', 'Needs review'

    finding = models.OneToOneField(CitationFinding, on_delete=models.CASCADE, related_name='review_decision')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='citation_review_decisions')
    decision = models.CharField(max_length=16, choices=Decision.choices)
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
