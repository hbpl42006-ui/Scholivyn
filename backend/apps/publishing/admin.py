from django.contrib import admin

from .models import (JournalMetadataSnapshot, JournalRecommendation, JournalRecommendationJob,
    ManuscriptProfile, PublicationReadinessAssessment, SavedJournal, SubmissionPreparation)


@admin.register(ManuscriptProfile)
class ManuscriptProfileAdmin(admin.ModelAdmin):
    list_display=('id','owner','document_version','updated_at')
    search_fields=('owner__email','document_version__original_filename')
    readonly_fields=('inferred','created_at','updated_at')


@admin.register(JournalMetadataSnapshot)
class JournalSnapshotAdmin(admin.ModelAdmin):
    list_display=('name','provider','provider_id','identity_status','verified_at')
    list_filter=('provider','identity_status','open_access','doaj_listed')
    search_fields=('name','provider_id','publisher')
    readonly_fields=('provider','provider_id','name','issns','publisher','website','subjects','open_access','doaj_listed',
        'works_count','publication_activity','source_url','raw_metadata','identity_status','discrepancies','verified_at')


@admin.register(JournalRecommendationJob)
class RecommendationJobAdmin(admin.ModelAdmin):
    list_display=('id','owner','status','progress','created_at')
    list_filter=('status','consent_to_external_metadata')
    search_fields=('owner__email','id')
    readonly_fields=('id','owner','profile','client_request_id','consent_to_external_metadata','preferences',
        'providers_completed','status','progress','result_count','error_category','created_at','updated_at','completed_at','lease_until')


@admin.register(JournalRecommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display=('job','journal','score','created_at')
    search_fields=('journal__name','job__owner__email')
    readonly_fields=('job','journal','score','factors','missing_evidence','created_at')


@admin.register(SavedJournal)
class SavedJournalAdmin(admin.ModelAdmin):
    list_display=('owner','journal','created_at')
    search_fields=('owner__email','journal__name')
    readonly_fields=('owner','journal','note','created_at')


@admin.register(PublicationReadinessAssessment)
class ReadinessAdmin(admin.ModelAdmin):
    list_display=('owner','document_version','updated_at')
    search_fields=('owner__email','document_version__original_filename')
    readonly_fields=('owner','document_version','checklist','summary','created_at','updated_at')


@admin.register(SubmissionPreparation)
class SubmissionAdmin(admin.ModelAdmin):
    list_display=('owner','document_version','status','updated_at')
    list_filter=('status',)
    search_fields=('owner__email','document_version__original_filename')
    readonly_fields=('owner','document_version','journal','created_at','updated_at')
