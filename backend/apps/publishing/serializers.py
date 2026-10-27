from rest_framework import serializers

from .models import (JournalMetadataSnapshot, JournalRecommendation, JournalRecommendationJob,
    ManuscriptProfile, PublicationReadinessAssessment, SavedJournal, SubmissionPreparation)


PROFILE_FIELDS = {'title','abstract','keywords','research_field','methodology','article_type','research_topics'}


class ProfileCreateSerializer(serializers.Serializer):
    document_version_id = serializers.UUIDField()


class ProfileCorrectionSerializer(serializers.Serializer):
    corrections = serializers.DictField()

    def validate_corrections(self, values):
        if set(values) - PROFILE_FIELDS:
            raise serializers.ValidationError('Only inferred profile fields can be corrected.')
        for key, value in values.items():
            if key in {'keywords','research_topics'}:
                if not isinstance(value, list) or len(value) > 40 or any(not isinstance(item, str) or len(item) > 200 for item in value):
                    raise serializers.ValidationError(f'{key} must be a list of at most 40 short text values.')
            elif not isinstance(value, str) or len(value) > (12000 if key in {'abstract','methodology'} else 500):
                raise serializers.ValidationError(f'{key} must be bounded text.')
        return values


class ProfileSerializer(serializers.ModelSerializer):
    document_version_id = serializers.UUIDField(read_only=True)
    document_id = serializers.UUIDField(source='document_version.document_id', read_only=True)
    project_id = serializers.UUIDField(source='document_version.document.project_id', read_only=True)
    project_title = serializers.CharField(source='document_version.document.project.title', read_only=True)
    original_filename = serializers.CharField(source='document_version.original_filename', read_only=True)
    revision_number = serializers.IntegerField(source='document_version.revision_number', read_only=True)
    metadata = serializers.SerializerMethodField()

    class Meta:
        model = ManuscriptProfile
        fields = ('id','document_version_id','document_id','project_id','project_title','original_filename','revision_number',
                  'inferred','corrections','metadata','created_at','updated_at')
        read_only_fields = fields

    def get_metadata(self, obj): return obj.metadata


class RecommendationInputSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField()
    client_request_id = serializers.UUIDField()
    consent_to_external_metadata = serializers.BooleanField()
    preferences = serializers.DictField(required=False, default=dict)

    def validate_preferences(self, value):
        if set(value) - {'open_access_required'} or ('open_access_required' in value and not isinstance(value['open_access_required'], bool)):
            raise serializers.ValidationError('Only the open_access_required preference is supported.')
        return value


class JournalSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalMetadataSnapshot
        fields = ('id','provider','provider_id','name','issns','publisher','website','subjects','open_access','doaj_listed',
                  'works_count','publication_activity','source_url','identity_status','discrepancies','verified_at')
        read_only_fields = fields


class RecommendationSerializer(serializers.ModelSerializer):
    journal = JournalSnapshotSerializer(read_only=True)
    class Meta:
        model = JournalRecommendation
        fields = ('id','journal','score','factors','missing_evidence','created_at')
        read_only_fields = fields


class RecommendationJobSerializer(serializers.ModelSerializer):
    profile_id = serializers.UUIDField(read_only=True)
    project_title = serializers.CharField(source='profile.document_version.document.project.title', read_only=True)
    original_filename = serializers.CharField(source='profile.document_version.original_filename', read_only=True)
    revision_number = serializers.IntegerField(source='profile.document_version.revision_number', read_only=True)
    recommendations = RecommendationSerializer(many=True, read_only=True)
    class Meta:
        model = JournalRecommendationJob
        fields = ('id','profile_id','project_title','original_filename','revision_number','client_request_id','preferences',
                  'consent_to_external_metadata','status','progress','result_count','error_category','recommendations',
                  'created_at','updated_at','completed_at')
        read_only_fields = fields


class SavedJournalSerializer(serializers.ModelSerializer):
    journal = JournalSnapshotSerializer(read_only=True)
    journal_id = serializers.IntegerField(write_only=True, min_value=1)
    class Meta:
        model = SavedJournal
        fields = ('id','journal','journal_id','note','created_at')
        read_only_fields = ('id','journal','created_at')


class ReadinessSerializer(serializers.ModelSerializer):
    document_version_id = serializers.UUIDField(read_only=True)
    original_filename = serializers.CharField(source='document_version.original_filename', read_only=True)
    project_title = serializers.CharField(source='document_version.document.project.title', read_only=True)
    revision_number = serializers.IntegerField(source='document_version.revision_number', read_only=True)
    class Meta:
        model = PublicationReadinessAssessment
        fields = ('id','document_version_id','original_filename','project_title','revision_number','checklist','summary','created_at','updated_at')
        read_only_fields = fields


class ReadinessInputSerializer(serializers.Serializer):
    document_version_id = serializers.UUIDField()


class SubmissionInputSerializer(serializers.Serializer):
    document_version_id = serializers.UUIDField()
    journal_id = serializers.IntegerField(required=False, allow_null=True)
    cover_letter = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=10000)
    required_files = serializers.ListField(child=serializers.CharField(max_length=200), required=False, max_length=30)
    checklist = serializers.ListField(child=serializers.DictField(), required=False, max_length=50)
    status = serializers.ChoiceField(choices=SubmissionPreparation.Status.choices, required=False)


class SubmissionSerializer(serializers.ModelSerializer):
    document_version_id = serializers.UUIDField(read_only=True)
    journal = JournalSnapshotSerializer(read_only=True)
    class Meta:
        model = SubmissionPreparation
        fields = ('id','document_version_id','journal','status','cover_letter','notes','required_files','checklist','created_at','updated_at')
        read_only_fields = ('id','document_version_id','journal','created_at','updated_at')
