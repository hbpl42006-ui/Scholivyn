from django.contrib import admin

from .models import SimilarityComparison, SimilarityJob, SimilarityMatch


class SimilarityComparisonInline(admin.TabularInline):
    model = SimilarityComparison
    extra = 0
    can_delete = False
    readonly_fields = ('target_version', 'status', 'exact_match_count', 'near_match_count', 'matched_source_words', 'created_at')
    fields = readonly_fields


@admin.register(SimilarityJob)
class SimilarityJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'source_version', 'status', 'progress', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('owner__username', 'owner__email', 'source_version__original_filename')
    readonly_fields = tuple(field.name for field in SimilarityJob._meta.fields)
    inlines = (SimilarityComparisonInline,)


@admin.register(SimilarityMatch)
class SimilarityMatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'comparison', 'match_type', 'similarity', 'citation_label')
    list_filter = ('match_type', 'citation_label')
    search_fields = ('source_section_title', 'target_section_title', 'source_paragraph_id', 'target_paragraph_id')
    readonly_fields = tuple(field.name for field in SimilarityMatch._meta.fields)


@admin.register(SimilarityComparison)
class SimilarityComparisonAdmin(admin.ModelAdmin):
    list_display = ('id', 'job', 'target_version', 'status', 'exact_match_count', 'near_match_count', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('job__owner__username', 'job__owner__email', 'target_version__original_filename')
    readonly_fields = tuple(field.name for field in SimilarityComparison._meta.fields)
