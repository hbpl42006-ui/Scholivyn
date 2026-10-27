from rest_framework import serializers

from apps.research.models import DocumentVersion
from .models import (BibliographicReference, CitationAnalysisJob, CitationFinding,
                     CitationMatch, CitationReviewDecision, ExtractedCitation, MetadataVerification)


class CitationAnalysisCreateSerializer(serializers.Serializer):
    document_version_id = serializers.UUIDField()
    client_request_id = serializers.UUIDField()
    citation_style = serializers.ChoiceField(choices=CitationAnalysisJob.Style.choices, default=CitationAnalysisJob.Style.AUTO)
    metadata_consent = serializers.BooleanField(default=False)

    def validate_document_version_id(self, value):
        request = self.context['request']
        version = DocumentVersion.objects.filter(pk=value, document__owner=request.user,
            document__project__owner=request.user).select_related('document__project').first()
        if version is None:
            raise serializers.ValidationError('The selected document version is unavailable in your workspace.')
        if version.processing_status != DocumentVersion.ProcessingStatus.COMPLETED:
            raise serializers.ValidationError('Document extraction must complete before citation analysis.')
        self.context['version'] = version
        return value


class CitationAnalysisJobSerializer(serializers.ModelSerializer):
    document_version_id = serializers.UUIDField(read_only=True)
    original_filename = serializers.CharField(source='document_version.original_filename', read_only=True)
    revision_number = serializers.IntegerField(source='document_version.revision_number', read_only=True)
    document_id = serializers.UUIDField(source='document_version.document_id', read_only=True)
    project_id = serializers.UUIDField(source='document_version.document.project_id', read_only=True)
    project_title = serializers.CharField(source='document_version.document.project.title', read_only=True)

    class Meta:
        model = CitationAnalysisJob
        fields = ('id','document_version_id','document_id','project_id','project_title','original_filename','revision_number',
            'client_request_id','citation_style','metadata_consent','metadata_status','status','progress','citation_count',
            'reference_count','matched_count','unmatched_count','ambiguous_count','incomplete_count','error_category',
            'error_message','created_at','updated_at','completed_at')
        read_only_fields = fields


class ExtractedCitationSerializer(serializers.ModelSerializer):
    match_status = serializers.SerializerMethodField()
    matched_reference_id = serializers.SerializerMethodField()

    class Meta:
        model = ExtractedCitation
        fields = ('id','style','raw_text','numeric_values','author_keys','years','section_key','section_title',
                  'paragraph_id','paragraph_index','start_offset','end_offset','match_status','matched_reference_id')
        read_only_fields = fields

    def get_match_status(self, obj):
        statuses = set(obj.matches.values_list('status', flat=True))
        if 'ambiguous' in statuses:
            return 'ambiguous'
        if 'unmatched' in statuses:
            return 'unmatched'
        if statuses and statuses == {'matched'}:
            return 'matched'
        return 'not_checked'

    def get_matched_reference_id(self, obj):
        match = obj.matches.filter(status='matched').select_related('reference').first()
        return match.reference_id if match else None


class MetadataVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetadataVerification
        fields = ('provider','status','confidence','source_url','metadata','error_category','verified_at')
        read_only_fields = fields


class BibliographicReferenceSerializer(serializers.ModelSerializer):
    metadata_checks = MetadataVerificationSerializer(many=True, read_only=True)
    match_status = serializers.SerializerMethodField()
    findings = serializers.SerializerMethodField()

    class Meta:
        model = BibliographicReference
        fields = ('id','raw_text','reference_number','authors','author_key','title','publication','year','doi',
                  'doi_normalized','urls','confidence','section_key','section_title','paragraph_id','paragraph_index',
                  'start_offset','end_offset','match_status','findings','metadata_checks')
        read_only_fields = fields

    def get_match_status(self, obj):
        return obj.matches.exclude(status='matched').first().status if obj.matches.exclude(status='matched').exists() else 'matched' if obj.matches.exists() else 'not_checked'

    def get_findings(self, obj):
        return list(obj.findings.values_list('code', flat=True))


class CitationMatchSerializer(serializers.ModelSerializer):
    citation_text = serializers.CharField(source='citation.raw_text', read_only=True, allow_null=True)
    reference_text = serializers.CharField(source='reference.raw_text', read_only=True, allow_null=True)
    reference_id = serializers.IntegerField(read_only=True, allow_null=True)
    citation_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = CitationMatch
        fields = ('id','citation_id','reference_id','citation_text','reference_text','status','issue_code','explanation')
        read_only_fields = fields


class CitationReviewDecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CitationReviewDecision
        fields = ('id','finding','decision','note','created_at','updated_at')
        read_only_fields = ('id','finding','created_at','updated_at')


class CitationFindingSerializer(serializers.ModelSerializer):
    review_decision = CitationReviewDecisionSerializer(read_only=True)
    excerpt = serializers.SerializerMethodField()

    class Meta:
        model = CitationFinding
        fields = ('id','citation_id','reference_id','code','severity','explanation','source_section_key',
                  'source_section_title','source_paragraph_id','source_paragraph_index','source_start','source_end',
                  'excerpt','review_decision','created_at')
        read_only_fields = fields

    def get_excerpt(self, obj):
        if obj.citation_id: return obj.citation.raw_text
        if obj.reference_id: return obj.reference.raw_text[:500]
        return ''


class CitationDecisionInputSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=CitationReviewDecision.Decision.choices)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
