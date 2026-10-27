from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from .models import DocumentVersion, ResearchDocument, ResearchProject


class ResearchProjectSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ResearchProject
        fields = ('id', 'title', 'description', 'research_field', 'keywords', 'status', 'created_at', 'updated_at', 'document_count')
        read_only_fields = ('id', 'created_at', 'updated_at', 'document_count')

    def validate_keywords(self, value):
        if not isinstance(value, list) or any(not isinstance(item, str) or len(item) > 80 for item in value):
            raise serializers.ValidationError('Keywords must be a list of short text values.')
        return value[:30]


class DocumentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentVersion
        fields = ('id', 'revision_number', 'original_filename', 'file_extension', 'mime_type', 'file_size',
                  'processing_status', 'processing_started_at', 'processing_error', 'processing_attempt', 'extraction_metadata',
                  'extraction_algorithm', 'reprocessed_from', 'uploaded_at')
        read_only_fields = fields


class ResearchDocumentSerializer(serializers.ModelSerializer):
    versions = DocumentVersionSerializer(many=True, read_only=True)
    current_version = serializers.SerializerMethodField()

    class Meta:
        model = ResearchDocument
        fields = ('id', 'project', 'original_filename', 'created_at', 'updated_at', 'current_version', 'versions')
        read_only_fields = fields

    @extend_schema_field(DocumentVersionSerializer(allow_null=True))
    def get_current_version(self, obj) -> dict | None:
        version = obj.current_version
        return DocumentVersionSerializer(version).data if version else None


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    document_id = serializers.UUIDField(required=False)


class DocumentMoveSerializer(serializers.Serializer):
    project = serializers.UUIDField()


class DocumentStatusSerializer(serializers.Serializer):
    document_id = serializers.UUIDField()
    version_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=DocumentVersion.ProcessingStatus.choices)
    processing_error = serializers.CharField(allow_blank=True)
    uploaded_at = serializers.DateTimeField()
    extraction_metadata = serializers.DictField()


class ResearchErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False)


class DocumentReprocessErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    version = DocumentVersionSerializer()


class DocumentMissingSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=('missing',))
