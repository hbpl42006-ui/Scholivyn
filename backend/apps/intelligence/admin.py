from django.contrib import admin

from .models import AIUsageRecord, AnalysisChunkResult, AnalysisIssue, AnalysisJob, AnalysisSectionResult, WritingSuggestion


@admin.register(AnalysisJob)
class AnalysisJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'document', 'reviewer_profile', 'status', 'progress', 'provider', 'model_identifier', 'created_at')
    list_filter = ('status', 'provider', 'reviewer_profile', 'created_at')
    search_fields = ('id', 'owner__username', 'owner__email', 'document__original_filename', 'project__title')
    readonly_fields = ('id', 'owner', 'project', 'document', 'document_version', 'analysis_type', 'reviewer_profile',
                       'status', 'progress', 'started_at', 'completed_at', 'error_category', 'error_message',
                       'provider', 'model_identifier', 'prompt_version', 'external_processing_consent',
                       'client_request_id', 'created_at', 'updated_at')
    fields = readonly_fields

    def has_add_permission(self, request):
        return False


@admin.register(AnalysisSectionResult)
class AnalysisSectionResultAdmin(admin.ModelAdmin):
    list_display = ('section_title', 'section_category', 'job', 'processing_status', 'completed_chunks', 'failed_chunks')
    list_filter = ('processing_status', 'section_category')
    search_fields = ('job__id', 'job__owner__email', 'section_title')
    readonly_fields = ('id', 'job', 'section_key', 'section_title', 'section_category', 'processing_status',
                       'completed_chunks', 'failed_chunks', 'created_at', 'updated_at')
    fields = readonly_fields

    def has_add_permission(self, request):
        return False


@admin.register(AnalysisIssue)
class AnalysisIssueAdmin(admin.ModelAdmin):
    # Evidence, explanation, and source passages are deliberately not shown in Admin.
    list_display = ('title', 'job', 'section', 'severity', 'category', 'resolution_status', 'created_at')
    list_filter = ('severity', 'category', 'resolution_status', 'created_at')
    search_fields = ('job__id', 'job__owner__email', 'title', 'category')
    readonly_fields = ('id', 'job', 'section', 'fingerprint', 'category', 'severity', 'title',
                       'resolution_status', 'created_at')
    fields = readonly_fields

    def has_add_permission(self, request):
        return False


@admin.register(WritingSuggestion)
class WritingSuggestionAdmin(admin.ModelAdmin):
    list_display = ('id', 'issue', 'document_version', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('issue__job__id', 'issue__job__owner__email')
    readonly_fields = ('id', 'issue', 'document_version', 'status', 'created_at', 'updated_at')
    fields = readonly_fields

    def has_add_permission(self, request):
        return False


@admin.register(AIUsageRecord)
class AIUsageRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'job', 'provider', 'model_identifier', 'input_tokens', 'output_tokens', 'reasoning_tokens', 'estimated_cost', 'processing_duration_ms', 'created_at')
    list_filter = ('provider', 'model_identifier', 'created_at')
    search_fields = ('user__email', 'user__username', 'job__id')
    readonly_fields = ('id', 'user', 'job', 'provider', 'model_identifier', 'request_key', 'input_tokens',
                       'output_tokens', 'reasoning_tokens', 'estimated_cost', 'processing_duration_ms', 'created_at')
    fields = readonly_fields

    def has_add_permission(self, request):
        return False


@admin.register(AnalysisChunkResult)
class AnalysisChunkResultAdmin(admin.ModelAdmin):
    list_display = ('job', 'section', 'chunk_index', 'status', 'error_category', 'updated_at')
    list_filter = ('status', 'error_category', 'updated_at')
    search_fields = ('job__id', 'section__section_title')
    readonly_fields = ('id', 'job', 'section', 'chunk_index', 'status', 'error_category', 'created_at', 'updated_at')
    fields = readonly_fields

    def has_add_permission(self, request):
        return False
