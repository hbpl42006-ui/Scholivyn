from rest_framework import serializers
from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema_field

from apps.intelligence.models import (AIUsageRecord, AnalysisIssue, AnalysisJob,
                                      AnalysisSectionResult, WritingSuggestion)


class AnalysisStartSerializer(serializers.Serializer):
    document_id = serializers.UUIDField()
    document_version_id = serializers.UUIDField()
    reviewer_profile = serializers.ChoiceField(choices=('general', 'computer_science', 'artificial_intelligence'), default='general')
    consent_to_external_processing = serializers.BooleanField()
    client_request_id = serializers.UUIDField(required=False)

    def validate_consent_to_external_processing(self, value):
        if not value:
            raise serializers.ValidationError('Consent is required before manuscript text is sent to the configured AI provider.')
        return value


class AnalysisJobSerializer(serializers.ModelSerializer):
    input_tokens = serializers.SerializerMethodField()
    output_tokens = serializers.SerializerMethodField()
    reasoning_tokens = serializers.SerializerMethodField()
    document_title = serializers.CharField(source='document.original_filename', read_only=True)
    project_title = serializers.CharField(source='project.title', read_only=True)
    chunk_counts = serializers.SerializerMethodField()

    @extend_schema_field(serializers.IntegerField())
    def get_input_tokens(self, obj) -> int:
        return getattr(obj, 'input_tokens', 0) or 0

    @extend_schema_field(serializers.IntegerField())
    def get_output_tokens(self, obj) -> int:
        return getattr(obj, 'output_tokens', 0) or 0

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_reasoning_tokens(self, obj) -> int | None:
        total_records = getattr(obj, 'usage_record_count', 0) or 0
        known_records = getattr(obj, 'reasoning_token_record_count', 0) or 0
        if total_records and total_records != known_records:
            return None
        return getattr(obj, 'reasoning_tokens', 0) or 0

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_chunk_counts(self, obj) -> dict[str, int]:
        counts = obj.chunks.aggregate(
            total=Count('id', filter=~Q(status='superseded')),
            completed=Count('id', filter=Q(status='completed')),
            failed=Count('id', filter=Q(status='failed')),
            pending=Count('id', filter=Q(status='queued')),
        )
        return counts

    class Meta:
        model = AnalysisJob
        fields = ('id', 'project', 'project_title', 'document', 'document_title', 'document_version', 'analysis_type', 'reviewer_profile',
                  'status', 'progress', 'started_at', 'completed_at', 'next_attempt_at', 'chunk_counts',
                  'error_category', 'error_message', 'provider', 'model_identifier', 'prompt_version',
                  'input_tokens', 'output_tokens', 'reasoning_tokens', 'created_at', 'updated_at')
        read_only_fields = fields


class WritingSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WritingSuggestion
        fields = ('id', 'original_text', 'suggested_text', 'explanation', 'status', 'source_paragraph_index')
        read_only_fields = fields


class AnalysisIssueSerializer(serializers.ModelSerializer):
    section_title = serializers.CharField(source='section.section_title', read_only=True)
    section_category = serializers.CharField(source='section.section_category', read_only=True)
    section_key = serializers.CharField(source='section.section_key', read_only=True)
    suggestion = WritingSuggestionSerializer(source='writing_suggestion', read_only=True)

    class Meta:
        model = AnalysisIssue
        fields = ('id', 'section_title', 'section_category', 'section_key', 'category', 'severity', 'title', 'explanation',
                  'evidence_snippet', 'source_paragraph_index', 'suggested_improvement', 'resolution_status', 'suggestion', 'created_at')
        read_only_fields = fields


class AnalysisSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisSectionResult
        fields = ('id', 'section_title', 'section_category', 'review_summary', 'strengths', 'weaknesses',
                  'recommendations', 'processing_status', 'completed_chunks', 'failed_chunks')
        read_only_fields = fields


class AnalysisIssueUpdateSerializer(serializers.Serializer):
    resolution_status = serializers.ChoiceField(choices=AnalysisIssue.Resolution.choices, required=False)
    suggestion_status = serializers.ChoiceField(choices=WritingSuggestion.Status.choices, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError('Provide a resolution or suggestion decision.')
        suggestion = attrs.get('suggestion_status')
        resolution = attrs.get('resolution_status')
        matching_resolution = {'accepted': 'accepted', 'rejected': 'rejected'}.get(suggestion)
        if matching_resolution and resolution in ('accepted', 'rejected') and resolution != matching_resolution:
            raise serializers.ValidationError({
                'resolution_status': 'The issue decision must match the writing-suggestion decision.',
            })
        return attrs


class AIUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIUsageRecord
        fields = ('provider', 'model_identifier', 'input_tokens', 'output_tokens', 'reasoning_tokens', 'estimated_cost',
                  'processing_duration_ms', 'created_at')
        read_only_fields = fields


class AnalysisReportAcknowledgementSerializer(serializers.Serializer):
    detail = serializers.CharField()
    download_url = serializers.CharField()


class AnalysisErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
