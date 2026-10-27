import uuid

from django.conf import settings
from django.db import models

from apps.research.models import DocumentVersion


class ManuscriptProfile(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='manuscript_profiles')
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='publishing_profiles')
    inferred = models.JSONField(default=dict)
    corrections = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('owner', 'document_version'), name='pub_profile_owner_version_uniq')]
        indexes = [models.Index(fields=('owner', 'updated_at'))]

    @property
    def metadata(self):
        return {**self.inferred, **self.corrections}


class JournalMetadataSnapshot(models.Model):
    class Provider(models.TextChoices):
        OPENALEX = 'openalex', 'OpenAlex'
        CROSSREF = 'crossref', 'Crossref'

    provider = models.CharField(max_length=16, choices=Provider.choices)
    provider_id = models.CharField(max_length=160)
    name = models.CharField(max_length=500)
    issns = models.JSONField(default=list, blank=True)
    publisher = models.CharField(max_length=500, blank=True)
    website = models.URLField(max_length=1000, blank=True)
    subjects = models.JSONField(default=list, blank=True)
    open_access = models.BooleanField(null=True, blank=True)
    doaj_listed = models.BooleanField(null=True, blank=True)
    works_count = models.PositiveBigIntegerField(null=True, blank=True)
    publication_activity = models.JSONField(default=list, blank=True)
    source_url = models.URLField(max_length=1000)
    raw_metadata = models.JSONField(default=dict, blank=True)
    identity_status = models.CharField(max_length=24, default='unverified')
    discrepancies = models.JSONField(default=list, blank=True)
    verified_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=('name',)), models.Index(fields=('verified_at',)), models.Index(fields=('provider','provider_id','verified_at'))]
        ordering = ('name', 'provider')


class JournalRecommendationJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        PARTIAL = 'partial', 'Partially completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='journal_recommendation_jobs')
    profile = models.ForeignKey(ManuscriptProfile, on_delete=models.PROTECT, related_name='recommendation_jobs')
    client_request_id = models.UUIDField()
    consent_to_external_metadata = models.BooleanField(default=False)
    preferences = models.JSONField(default=dict, blank=True)
    providers_completed = models.JSONField(default=list, blank=True)
    journal_snapshots = models.ManyToManyField('JournalMetadataSnapshot', related_name='recommendation_jobs', blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    progress = models.PositiveSmallIntegerField(default=0)
    result_count = models.PositiveSmallIntegerField(default=0)
    error_category = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [models.UniqueConstraint(fields=('owner', 'client_request_id'), name='pub_job_owner_request_uniq')]
        indexes = [models.Index(fields=('owner', 'status')), models.Index(fields=('status', 'created_at'))]


class JournalRecommendation(models.Model):
    job = models.ForeignKey(JournalRecommendationJob, on_delete=models.CASCADE, related_name='recommendations')
    journal = models.ForeignKey(JournalMetadataSnapshot, on_delete=models.PROTECT, related_name='recommendations')
    score = models.PositiveSmallIntegerField()
    factors = models.JSONField(default=dict)
    missing_evidence = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('job', 'journal'), name='pub_job_journal_uniq')]
        ordering = ('-score', 'journal__name')


class SavedJournal(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_journals')
    journal = models.ForeignKey(JournalMetadataSnapshot, on_delete=models.PROTECT, related_name='saved_by')
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('owner', 'journal'), name='pub_saved_journal_owner_uniq')]


class PublicationReadinessAssessment(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='readiness_assessments')
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='readiness_assessments')
    checklist = models.JSONField(default=list)
    summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('owner', 'document_version'), name='pub_readiness_owner_version_uniq')]
        indexes = [models.Index(fields=('owner', 'updated_at'))]


class SubmissionPreparation(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        PREPARING = 'preparing', 'Preparing'
        READY_FOR_MANUAL_REVIEW = 'ready_for_manual_review', 'Ready for manual review'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='submission_preparations')
    document_version = models.ForeignKey(DocumentVersion, on_delete=models.PROTECT, related_name='submission_preparations')
    journal = models.ForeignKey(JournalMetadataSnapshot, null=True, blank=True, on_delete=models.PROTECT, related_name='submission_preparations')
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    cover_letter = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    required_files = models.JSONField(default=list, blank=True)
    checklist = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('owner', 'document_version'), name='pub_submission_owner_version_uniq')]
        indexes = [models.Index(fields=('owner', 'status'))]
