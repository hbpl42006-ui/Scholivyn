from django.contrib import admin

from .models import DocumentVersion, ResearchDocument, ResearchProject


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    can_delete = False
    readonly_fields = ('revision_number', 'original_filename', 'file_extension', 'mime_type', 'file_size', 'extraction_algorithm', 'processing_status', 'uploaded_at')
    fields = readonly_fields


@admin.register(ResearchProject)
class ResearchProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'research_field', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'research_field', 'created_at')
    search_fields = ('title', 'owner__username', 'owner__email', 'research_field')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(ResearchDocument)
class ResearchDocumentAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'project', 'owner', 'current_status', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('original_filename', 'owner__username', 'owner__email', 'project__title')
    readonly_fields = ('id', 'project', 'owner', 'original_filename', 'created_at', 'updated_at')
    inlines = (DocumentVersionInline,)

    @admin.display(description='Processing status')
    def current_status(self, obj):
        version = obj.current_version
        return version.processing_status if version else '—'


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ('document', 'revision_number', 'extraction_algorithm', 'file_extension', 'file_size', 'processing_status', 'uploaded_at')
    list_filter = ('processing_status', 'file_extension', 'uploaded_at')
    search_fields = ('original_filename', 'document__original_filename', 'document__project__title', 'document__owner__email')
    readonly_fields = ('id', 'document', 'revision_number', 'original_filename', 'file_extension', 'mime_type', 'file_size', 'storage_key', 'extraction_algorithm', 'reprocessed_from', 'processing_status', 'extraction_metadata', 'uploaded_at')
