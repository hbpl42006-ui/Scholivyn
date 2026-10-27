from io import BytesIO
import logging
from xml.sax.saxutils import escape

from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from apps.research.models import DocumentVersion
from .models import (JournalMetadataSnapshot, JournalRecommendationJob, ManuscriptProfile,
    PublicationReadinessAssessment, SavedJournal, SubmissionPreparation)
from .serializers import (ProfileCreateSerializer, ProfileCorrectionSerializer, ProfileSerializer,
    ReadinessInputSerializer, ReadinessSerializer, RecommendationInputSerializer,
    RecommendationJobSerializer, SavedJournalSerializer, SubmissionInputSerializer, SubmissionSerializer)
from .services.profiling import get_or_create_profile, save_readiness
from .tasks import process_journal_recommendation
from apps.billing.services.entitlements import BillingError, reserve_usage, release_reservation
from apps.billing.services.usage import billing_http_status

logger = logging.getLogger(__name__)
PAGE_SIZE = 50


def _owned_version(user, version_id):
    return get_object_or_404(DocumentVersion.objects.select_related('document__project'), pk=version_id,
        document__owner=user, document__project__owner=user,
        processing_status=DocumentVersion.ProcessingStatus.COMPLETED)


def _owned_job(user, job_id):
    return get_object_or_404(JournalRecommendationJob.objects.select_related('profile__document_version__document__project').prefetch_related('recommendations__journal'),
        pk=job_id, owner=user)


def _enqueue(job):
    try:
        process_journal_recommendation.apply_async(args=(str(job.pk),), queue='celery')
    except Exception as exc:
        logger.warning('Publishing job enqueue failed type=%s', type(exc).__name__,
                       extra={'recommendation_job_id':str(job.pk),'error_category':'queue_unavailable'})
        reservation = __import__('apps.billing.models', fromlist=['CreditReservation']).CreditReservation.objects.filter(
            reference_type='journal_job', reference_id=str(job.pk)).first()
        release_reservation(reservation)
        job.status = JournalRecommendationJob.Status.FAILED
        job.error_category = 'queue_unavailable'
        job.completed_at = timezone.now()
        job.save(update_fields=('status','error_category','completed_at','updated_at'))


class ProfileListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=ProfileSerializer(many=True))
    def get(self, request):
        rows = ManuscriptProfile.objects.filter(owner=request.user).select_related('document_version__document__project')[:PAGE_SIZE]
        return Response(ProfileSerializer(rows, many=True).data)

    @extend_schema(request=ProfileCreateSerializer, responses={200:ProfileSerializer,201:ProfileSerializer})
    def post(self, request):
        serializer = ProfileCreateSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        version = _owned_version(request.user, serializer.validated_data['document_version_id'])
        profile, created = get_or_create_profile(request.user, version)
        return Response(ProfileSerializer(profile).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ProfileDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self, request, profile_id):
        return get_object_or_404(ManuscriptProfile.objects.select_related('document_version__document__project'),
                                 pk=profile_id, owner=request.user)

    @extend_schema(responses=ProfileSerializer)
    def get(self, request, profile_id): return Response(ProfileSerializer(self.get_object(request, profile_id)).data)

    @extend_schema(request=ProfileCorrectionSerializer, responses=ProfileSerializer)
    def patch(self, request, profile_id):
        profile = self.get_object(request, profile_id)
        serializer = ProfileCorrectionSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        profile.corrections = {**profile.corrections, **serializer.validated_data['corrections']}
        profile.save(update_fields=('corrections','updated_at'))
        return Response(ProfileSerializer(profile).data)


class RecommendationListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    pagination_class = LimitOffsetPagination

    @extend_schema(responses=RecommendationJobSerializer(many=True))
    def get(self, request):
        paginator = self.pagination_class(); paginator.default_limit = 20; paginator.max_limit = 50
        page = paginator.paginate_queryset(JournalRecommendationJob.objects.filter(owner=request.user).select_related(
            'profile__document_version__document__project').prefetch_related('recommendations__journal'), request)
        return paginator.get_paginated_response(RecommendationJobSerializer(page, many=True).data)

    @extend_schema(request=RecommendationInputSerializer, responses={201:RecommendationJobSerializer,200:RecommendationJobSerializer,400:OpenApiResponse(description='Invalid profile or missing explicit provider consent.')})
    def post(self, request):
        serializer = RecommendationInputSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        profile = get_object_or_404(ManuscriptProfile.objects.select_related('document_version'),
                                    pk=data['profile_id'], owner=request.user)
        if not data['consent_to_external_metadata']:
            return Response({'consent_to_external_metadata':['Explicit consent is required to send a short query derived from title, research field, keywords and inferred topics to journal metadata providers.']}, status=400)
        try:
            with transaction.atomic():
                job, created = JournalRecommendationJob.objects.get_or_create(owner=request.user,
                    client_request_id=data['client_request_id'], defaults={'profile':profile,
                    'consent_to_external_metadata':True,'preferences':data.get('preferences') or {}})
                if not created and (job.profile_id != profile.pk or job.preferences != (data.get('preferences') or {}) or not job.consent_to_external_metadata):
                    return Response({'detail':'This idempotency key was already used for a different recommendation request.'},status=409)
                if created:
                    reserve_usage(request.user, feature='journal_recommendation',
                        idempotency_key=f"journal:{data['client_request_id']}", units=1,
                        reference_type='journal_job', reference_id=str(job.pk))
                    transaction.on_commit(lambda: _enqueue(job))
        except IntegrityError:
            job = JournalRecommendationJob.objects.get(owner=request.user, client_request_id=data['client_request_id'])
            created = False
        except BillingError as exc:
            return Response({'detail': str(exc), 'code': 'billing_error'}, status=billing_http_status(exc))
        return Response(RecommendationJobSerializer(job).data, status=201 if created else 200)


class RecommendationDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=RecommendationJobSerializer)
    def get(self, request, job_id):
        job = _owned_job(request.user, job_id)
        return Response(RecommendationJobSerializer(job).data)


class RecommendationActionView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200:RecommendationJobSerializer,409:OpenApiResponse(description='Action is not valid for the current status.')})
    def post(self, request, job_id, action):
        job = _owned_job(request.user, job_id)
        if action == 'cancel':
            changed = JournalRecommendationJob.objects.filter(pk=job.pk, owner=request.user,
                status__in=(JournalRecommendationJob.Status.QUEUED,JournalRecommendationJob.Status.PROCESSING)).update(
                status=JournalRecommendationJob.Status.CANCELLED, completed_at=timezone.now(), lease_until=None)
            if not changed: return Response({'detail':'Only queued or processing jobs can be cancelled.'}, status=409)
        elif action == 'retry':
            changed = JournalRecommendationJob.objects.filter(pk=job.pk, owner=request.user,
                status__in=(JournalRecommendationJob.Status.FAILED,JournalRecommendationJob.Status.PARTIAL)).update(
                status=JournalRecommendationJob.Status.QUEUED, error_category='', completed_at=None, lease_until=None, progress=0)
            if not changed: return Response({'detail':'Only failed or partial jobs can be retried.'}, status=409)
            transaction.on_commit(lambda: _enqueue(job))
        else: return Response({'detail':'Unknown action.'}, status=404)
        return Response(RecommendationJobSerializer(_owned_job(request.user, job.pk)).data)


class SavedJournalListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        rows = SavedJournal.objects.filter(owner=request.user).select_related('journal').order_by('-created_at')[:200]
        return Response(SavedJournalSerializer(rows, many=True).data)

    @extend_schema(request=SavedJournalSerializer, responses={201:SavedJournalSerializer,400:OpenApiResponse(description='Journal is not in this user\'s recommendation history.')})
    def post(self, request):
        serializer = SavedJournalSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        journal_id = serializer.validated_data['journal_id']
        journal = get_object_or_404(JournalMetadataSnapshot, pk=journal_id, recommendations__job__owner=request.user)
        item, created = SavedJournal.objects.get_or_create(owner=request.user,journal=journal,
            defaults={'note':serializer.validated_data.get('note','')})
        return Response(SavedJournalSerializer(item).data,status=201 if created else 200)


class SavedJournalDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def delete(self, request, saved_id):
        item = get_object_or_404(SavedJournal,pk=saved_id,owner=request.user); item.delete()
        return Response(status=204)


class ReadinessListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        rows = PublicationReadinessAssessment.objects.filter(owner=request.user).select_related('document_version__document__project')[:100]
        return Response(ReadinessSerializer(rows,many=True).data)

    @extend_schema(request=ReadinessInputSerializer, responses={200:ReadinessSerializer,201:ReadinessSerializer})
    def post(self, request):
        serializer = ReadinessInputSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        version = _owned_version(request.user, serializer.validated_data['document_version_id'])
        assessment = save_readiness(request.user,version)
        return Response(ReadinessSerializer(assessment).data,status=200)


class SubmissionPreparationView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        version_id = request.query_params.get('document_version_id')
        if not version_id: return Response({'document_version_id':['This query parameter is required.']},status=400)
        version = _owned_version(request.user,version_id)
        profile = get_or_create_profile(request.user, version)
        obj, _ = SubmissionPreparation.objects.get_or_create(owner=request.user,document_version=version)
        if not obj.cover_letter:
            title = profile.metadata.get('title') or '[Manuscript title]'
            obj.cover_letter = (f'Dear [Editor name],\n\nPlease consider our manuscript “{title}” for publication. '
                'Please replace this draft with journal-specific details and verify all statements before use.\n\n'
                'Sincerely,\n[Corresponding author name]\n[Affiliation and contact information]')
            obj.save(update_fields=('cover_letter','updated_at'))
        return Response(SubmissionSerializer(obj).data)

    @extend_schema(request=SubmissionInputSerializer, responses=SubmissionSerializer)
    def put(self, request):
        serializer = SubmissionInputSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        data=serializer.validated_data; version=_owned_version(request.user,data['document_version_id'])
        journal = None
        if data.get('journal_id') is not None:
            journal = get_object_or_404(JournalMetadataSnapshot,pk=data['journal_id'],
                recommendations__job__owner=request.user)
        obj,_=SubmissionPreparation.objects.get_or_create(owner=request.user,document_version=version)
        for key in ('cover_letter','notes','required_files','checklist','status'):
            if key in data: setattr(obj,key,data[key])
        obj.journal=journal
        obj.save()
        return Response(SubmissionSerializer(obj).data)


class ReadinessReportView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={200:OpenApiResponse(response=OpenApiTypes.BINARY,description='Owner-authorized publication readiness PDF.')})
    def get(self,request,assessment_id):
        assessment=get_object_or_404(PublicationReadinessAssessment.objects.select_related('document_version__document__project'),
            pk=assessment_id,owner=request.user)
        buffer=BytesIO(); styles=getSampleStyleSheet()
        doc=SimpleDocTemplate(buffer,pagesize=letter,rightMargin=.65*inch,leftMargin=.65*inch,topMargin=.65*inch,bottomMargin=.65*inch)
        story=[Paragraph('Scholivyn — Publication readiness',styles['Title']),
            Paragraph(f'Manuscript: {escape(assessment.document_version.original_filename)} · revision {assessment.document_version.revision_number}',styles['BodyText']),
            Paragraph('This checklist is guidance, not a journal-specific compliance determination or guarantee.',styles['BodyText']),Spacer(1,10)]
        for item in assessment.checklist:
            story.extend((Paragraph(f"{escape(str(item.get('label','')))} — {escape(str(item.get('status','')))}",styles['Heading3']),
                Paragraph(escape(str(item.get('detail',''))),styles['BodyText']),Spacer(1,5)))
        doc.build(story); buffer.seek(0)
        return FileResponse(buffer,as_attachment=True,filename=f'scholivyn-readiness-{assessment.pk}.pdf',content_type='application/pdf')
