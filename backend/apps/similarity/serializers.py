from rest_framework import serializers

from .models import SimilarityComparison, SimilarityJob, SimilarityMatch


class SimilarityCreateSerializer(serializers.Serializer):
    source_version_id = serializers.UUIDField()
    target_version_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    client_request_id = serializers.UUIDField()

    def validate_target_version_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError('Choose each target version only once.')
        return value


class SimilarityMatchSerializer(serializers.ModelSerializer):
    source_text = serializers.SerializerMethodField()
    target_text = serializers.SerializerMethodField()
    source_match_text = serializers.SerializerMethodField()
    target_match_text = serializers.SerializerMethodField()
    source_before = serializers.SerializerMethodField()
    source_after = serializers.SerializerMethodField()
    target_before = serializers.SerializerMethodField()
    target_after = serializers.SerializerMethodField()
    source_filename = serializers.CharField(source='comparison.job.source_version.original_filename')
    target_filename = serializers.CharField(source='comparison.target_version.original_filename')
    source_revision = serializers.IntegerField(source='comparison.job.source_version.revision_number')
    target_revision = serializers.IntegerField(source='comparison.target_version.revision_number')

    class Meta:
        model = SimilarityMatch
        fields = ('id', 'match_type', 'similarity', 'source_word_count', 'citation_label',
                  'source_section_key', 'source_section_title', 'source_paragraph_id', 'source_paragraph_index',
                  'source_start', 'source_end', 'source_text', 'source_match_text', 'source_before', 'source_after', 'source_filename', 'source_revision',
                  'target_section_key', 'target_section_title', 'target_paragraph_id', 'target_paragraph_index',
                  'target_start', 'target_end', 'target_text', 'target_match_text', 'target_before', 'target_after', 'target_filename', 'target_revision')

    @staticmethod
    def _paragraph(version, section_key, paragraph_id, paragraph_index):
        metadata = version.extraction_metadata or {}
        for section in metadata.get('sections') or []:
            if str(section.get('section_key') or '') != section_key:
                continue
            records = section.get('paragraph_records') or []
            for index, record in enumerate(records):
                if paragraph_id and record.get('source_id') == paragraph_id:
                    return str(record.get('text') or '')
                if not paragraph_id and int(record.get('paragraph_index') if record.get('paragraph_index') is not None else index) == paragraph_index:
                    return str(record.get('text') or '')
            paragraphs = section.get('paragraphs') or []
            if paragraph_index < len(paragraphs):
                return str(paragraphs[paragraph_index])
        if section_key == 'unclassified':
            records = metadata.get('unclassified') or []
            if paragraph_index < len(records):
                return str(records[paragraph_index].get('text') or '')
        return ''

    def get_source_text(self, obj):
        version = obj.comparison.job.source_version
        text = self._paragraph(version, obj.source_section_key, obj.source_paragraph_id, obj.source_paragraph_index)
        return text[max(0, obj.source_start - 100):min(len(text), obj.source_end + 100)]

    def get_target_text(self, obj):
        version = obj.comparison.target_version
        text = self._paragraph(version, obj.target_section_key, obj.target_paragraph_id, obj.target_paragraph_index)
        return text[max(0, obj.target_start - 100):min(len(text), obj.target_end + 100)]

    def get_source_match_text(self, obj):
        text = self._paragraph(obj.comparison.job.source_version, obj.source_section_key,
                               obj.source_paragraph_id, obj.source_paragraph_index)
        return text[obj.source_start:obj.source_end]

    def get_target_match_text(self, obj):
        text = self._paragraph(obj.comparison.target_version, obj.target_section_key,
                               obj.target_paragraph_id, obj.target_paragraph_index)
        return text[obj.target_start:obj.target_end]

    def get_source_before(self, obj):
        text = self._paragraph(obj.comparison.job.source_version, obj.source_section_key,
                               obj.source_paragraph_id, obj.source_paragraph_index)
        return text[max(0, obj.source_start - 100):obj.source_start]

    def get_source_after(self, obj):
        text = self._paragraph(obj.comparison.job.source_version, obj.source_section_key,
                               obj.source_paragraph_id, obj.source_paragraph_index)
        return text[obj.source_end:min(len(text), obj.source_end + 100)]

    def get_target_before(self, obj):
        text = self._paragraph(obj.comparison.target_version, obj.target_section_key,
                               obj.target_paragraph_id, obj.target_paragraph_index)
        return text[max(0, obj.target_start - 100):obj.target_start]

    def get_target_after(self, obj):
        text = self._paragraph(obj.comparison.target_version, obj.target_section_key,
                               obj.target_paragraph_id, obj.target_paragraph_index)
        return text[obj.target_end:min(len(text), obj.target_end + 100)]


class SimilarityComparisonSerializer(serializers.ModelSerializer):
    target_document_title = serializers.CharField(source='target_version.document.original_filename')
    target_project_title = serializers.CharField(source='target_version.document.project.title')
    target_version_id = serializers.UUIDField(source='target_version.id')
    target_document_id = serializers.UUIDField(source='target_version.document.id')
    target_project_id = serializers.UUIDField(source='target_version.document.project.id')
    matches = SimilarityMatchSerializer(many=True, read_only=True)

    class Meta:
        model = SimilarityComparison
        fields = ('id', 'target_version_id', 'target_document_id', 'target_project_id', 'target_document_title', 'target_project_title', 'status',
                  'exact_match_count', 'near_match_count', 'matched_source_words', 'matches')


class SimilarityJobSerializer(serializers.ModelSerializer):
    source_document_title = serializers.CharField(source='source_version.document.original_filename')
    source_project_title = serializers.CharField(source='source_version.document.project.title')
    source_version_id = serializers.UUIDField(source='source_version.id')
    source_document_id = serializers.UUIDField(source='source_version.document.id')
    source_project_id = serializers.UUIDField(source='source_version.document.project.id')
    source_revision = serializers.IntegerField(source='source_version.revision_number')
    comparisons = SimilarityComparisonSerializer(many=True, read_only=True)

    class Meta:
        model = SimilarityJob
        fields = ('id', 'source_version_id', 'source_document_id', 'source_project_id', 'source_revision', 'source_document_title', 'source_project_title', 'status',
                  'progress', 'total_targets', 'completed_targets', 'exact_match_count', 'near_match_count',
                  'matched_source_words', 'source_word_count', 'matched_percentage', 'error_message',
                  'created_at', 'updated_at', 'completed_at', 'comparisons')
