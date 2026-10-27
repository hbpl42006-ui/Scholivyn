from django.contrib import admin

from .models import (BibliographicReference, CitationAnalysisJob, CitationFinding, CitationMatch,
                     CitationReviewDecision, ExtractedCitation, MetadataVerification)


@admin.register(CitationAnalysisJob)
class CitationAnalysisJobAdmin(admin.ModelAdmin):
    list_display = ('id','owner','document_version','status','metadata_status','progress','created_at')
    list_filter = ('status','citation_style','metadata_status','created_at')
    search_fields = ('owner__username','owner__email','document_version__original_filename','id')
    readonly_fields = tuple(field.name for field in CitationAnalysisJob._meta.fields)


@admin.register(ExtractedCitation)
class ExtractedCitationAdmin(admin.ModelAdmin):
    list_display = ('id','job','style','section_title','paragraph_index','start_offset')
    list_filter = ('style',)
    search_fields = ('raw_text','job__owner__email')
    readonly_fields = tuple(field.name for field in ExtractedCitation._meta.fields)


@admin.register(BibliographicReference)
class BibliographicReferenceAdmin(admin.ModelAdmin):
    list_display = ('id','job','reference_number','title','year','doi_normalized')
    search_fields = ('title','raw_text','doi_normalized','job__owner__email')
    readonly_fields = tuple(field.name for field in BibliographicReference._meta.fields)


@admin.register(CitationMatch)
class CitationMatchAdmin(admin.ModelAdmin):
    list_display = ('id','job','status','issue_code','created_at')
    list_filter = ('status','issue_code')
    readonly_fields = tuple(field.name for field in CitationMatch._meta.fields)


@admin.register(CitationFinding)
class CitationFindingAdmin(admin.ModelAdmin):
    list_display = ('id','job','code','severity','created_at')
    list_filter = ('severity','code')
    search_fields = ('explanation','job__owner__email')
    readonly_fields = tuple(field.name for field in CitationFinding._meta.fields)


@admin.register(MetadataVerification)
class MetadataVerificationAdmin(admin.ModelAdmin):
    list_display = ('id','reference','provider','status','verified_at')
    list_filter = ('provider','status')
    readonly_fields = tuple(field.name for field in MetadataVerification._meta.fields)


@admin.register(CitationReviewDecision)
class CitationReviewDecisionAdmin(admin.ModelAdmin):
    list_display = ('id','owner','finding','decision','updated_at')
    list_filter = ('decision',)
    search_fields = ('owner__email','note')
    readonly_fields = tuple(field.name for field in CitationReviewDecision._meta.fields)
