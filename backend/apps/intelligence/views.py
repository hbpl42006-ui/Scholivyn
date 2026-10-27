from io import BytesIO

from django.db import IntegrityError, transaction
from django.conf import settings
from django.db.models import Count, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.research.models import DocumentVersion, ResearchDocument
from apps.intelligence.models import (AnalysisChunkResult, AnalysisIssue, AnalysisJob,
                                      AnalysisSectionResult, WritingSuggestion)
from apps.intelligence.serializers import (AnalysisIssueSerializer, AnalysisIssueUpdateSerializer,
    AnalysisJobSerializer, AnalysisSectionSerializer, AnalysisStartSerializer, AIUsageSerializer)
from apps.intelligence.serializers import (AnalysisErrorResponseSerializer,
    AnalysisReportAcknowledgementSerializer)
from apps.intelligence.services.providers.factory import ai_configuration_error
from apps.intelligence.services.prompts.system import PROMPT_VERSION
from apps.intelligence.tasks import process_analysis_job
from apps.billing.services.entitlements import BillingError, FeatureUnavailable, InsufficientCredits, reserve_usage, release_reservation


def owned_jobs(user):
    return AnalysisJob.objects.filter(owner=user).select_related('project', 'document', 'document_version').annotate(
        input_tokens=Sum('usage_records__input_tokens'), output_tokens=Sum('usage_records__output_tokens'),
        reasoning_tokens=Sum('usage_records__reasoning_tokens'),
        usage_record_count=Count('usage_records'),
        reasoning_token_record_count=Count('usage_records__reasoning_tokens'))


class AnalysisListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'ai_analysis'

    def get_throttles(self):
        # Keep the existing ai_analysis scope/key for POST so its quota and
        # cooldown are preserved. Read-only methods use their separate scope.
        self.throttle_scope = 'ai_analysis' if self.request.method == 'POST' else 'ai_analysis_read'
        return super().get_throttles()

    @extend_schema(responses=AnalysisJobSerializer(many=True))
    def get(self, request):
        jobs = owned_jobs(request.user)
        document_id = request.query_params.get('document_id')
        if document_id:
            jobs = jobs.filter(document_id=document_id)
        return Response(AnalysisJobSerializer(jobs[:100], many=True).data)

    @extend_schema(request=AnalysisStartSerializer, responses={202: AnalysisJobSerializer, 400: None, 503: None})
    def post(self, request):
        unavailable = ai_configuration_error()
        if unavailable:
            return Response({'detail': unavailable, 'code': 'ai_not_configured'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        serializer = AnalysisStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        document = get_object_or_404(ResearchDocument, pk=values['document_id'], owner=request.user)
        version = get_object_or_404(DocumentVersion, pk=values['document_version_id'], document=document)
        if version.processing_status != DocumentVersion.ProcessingStatus.COMPLETED:
            return Response({'detail': 'Document extraction must be complete before analysis can start.'}, status=400)
        request_id = values.get('client_request_id')
        if request_id:
            existing = AnalysisJob.objects.filter(owner=request.user, client_request_id=request_id).first()
            if existing:
                if existing.document_id != document.pk or existing.document_version_id != version.pk:
                    return Response({'detail': 'This request identifier is already used for a different document.'}, status=409)
                return Response(AnalysisJobSerializer(existing).data, status=202)
        try:
            with transaction.atomic():
                # Serialize start requests per account so parallel clicks cannot
                # exceed the configured active-job limit on PostgreSQL.
                from django.contrib.auth import get_user_model
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
                active = AnalysisJob.objects.filter(owner=request.user, status__in=(
                    AnalysisJob.Status.QUEUED, AnalysisJob.Status.PROCESSING, AnalysisJob.Status.WAITING_FOR_QUOTA,
                )).count()
                if active >= settings.AI_MAX_ACTIVE_JOBS_PER_USER:
                    return Response({'detail': 'An analysis is already queued or processing for this account.'}, status=429)
                if request_id:
                    existing = AnalysisJob.objects.filter(owner=request.user, client_request_id=request_id).first()
                    if existing:
                        return Response(AnalysisJobSerializer(existing).data, status=202)
                job = AnalysisJob.objects.create(
                    owner=request.user, project=document.project, document=document, document_version=version,
                    reviewer_profile=values['reviewer_profile'], provider=settings.AI_PROVIDER, model_identifier=settings.AI_MODEL,
                    prompt_version=PROMPT_VERSION,
                    external_processing_consent=True, client_request_id=request_id,
                    chunk_token_limit=(
                        max(128, min(settings.AI_MAX_CHUNK_TOKENS,
                                     settings.GROQ_TPM_LIMIT - settings.AI_MAX_OUTPUT_TOKENS - 1500))
                        if settings.AI_PROVIDER == 'groq' else settings.AI_MAX_CHUNK_TOKENS
                    ),
                )
        except IntegrityError:
            if request_id:
                job = AnalysisJob.objects.get(owner=request.user, client_request_id=request_id)
            else:
                raise
        try:
            reserve_usage(request.user, feature='ai_review', idempotency_key=f'analysis:{job.pk}',
                units=1, reference_type='analysis_job', reference_id=str(job.pk))
        except FeatureUnavailable as exc:
            job.delete()
            return Response({'detail': str(exc), 'code': 'feature_unavailable'}, status=403)
        except InsufficientCredits as exc:
            job.delete()
            return Response({'detail': str(exc), 'code': 'insufficient_credits'}, status=402)
        except BillingError as exc:
            job.delete()
            return Response({'detail': str(exc), 'code': 'billing_error'}, status=409)
        try:
            process_analysis_job.delay(str(job.pk))
        except Exception:
            reservation = __import__('apps.billing.models', fromlist=['CreditReservation']).CreditReservation.objects.filter(
                reference_type='analysis_job', reference_id=str(job.pk)).first()
            release_reservation(reservation)
            job.status = AnalysisJob.Status.FAILED
            job.error_category = 'queue_unavailable'
            job.error_message = 'The analysis queue is temporarily unavailable. Please try again.'
            job.save(update_fields=('status', 'error_category', 'error_message', 'updated_at'))
            return Response(AnalysisJobSerializer(job).data, status=503)
        return Response(AnalysisJobSerializer(job).data, status=202)


class AnalysisDetailView(generics.RetrieveAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = AnalysisJobSerializer

    def get_queryset(self):
        return owned_jobs(self.request.user)


class AnalysisStatusView(generics.RetrieveAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = AnalysisJobSerializer

    def get_queryset(self):
        return owned_jobs(self.request.user)


class AnalysisSectionsView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = AnalysisSectionSerializer

    def get_queryset(self):
        get_object_or_404(AnalysisJob, pk=self.kwargs['pk'], owner=self.request.user)
        return AnalysisSectionResult.objects.filter(job_id=self.kwargs['pk'], job__owner=self.request.user).prefetch_related('issues')


class IssuePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class AnalysisIssuesView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = AnalysisIssueSerializer
    pagination_class = IssuePagination

    def get_queryset(self):
        job = get_object_or_404(AnalysisJob, pk=self.kwargs['pk'], owner=self.request.user)
        queryset = AnalysisIssue.objects.filter(job=job).select_related('section').select_related('writing_suggestion')
        for query, field in (('severity', 'severity'), ('category', 'category'), ('resolution', 'resolution_status')):
            value = self.request.query_params.get(query)
            if value:
                queryset = queryset.filter(**{field: value})
        section = self.request.query_params.get('section')
        if section:
            queryset = queryset.filter(section__section_category=section)
        search = self.request.query_params.get('search', '').strip()[:120]
        if search:
            queryset = queryset.filter(title__icontains=search) | queryset.filter(explanation__icontains=search)
        return queryset.distinct()


class AnalysisIssueUpdateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(request=AnalysisIssueUpdateSerializer, responses=AnalysisIssueSerializer)
    def patch(self, request, issue_id):
        serializer = AnalysisIssueUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        with transaction.atomic():
            issue = get_object_or_404(
                AnalysisIssue.objects.select_for_update().select_related('job'),
                pk=issue_id, job__owner=request.user,
            )
            if 'suggestion_status' in values:
                suggestion = getattr(issue, 'writing_suggestion', None)
                if not suggestion:
                    return Response({'detail': 'This finding does not have a writing suggestion.'}, status=400)
                suggestion.status = values['suggestion_status']
                suggestion.save(update_fields=('status', 'updated_at'))
                mapped = {
                    'proposed': AnalysisIssue.Resolution.OPEN,
                    'accepted': AnalysisIssue.Resolution.ACCEPTED,
                    'rejected': AnalysisIssue.Resolution.REJECTED,
                }
                issue.resolution_status = mapped[suggestion.status]
            if 'resolution_status' in values:
                issue.resolution_status = values['resolution_status']
            issue.save(update_fields=('resolution_status',))
        return Response(AnalysisIssueSerializer(issue).data)


class AnalysisCancelView(APIView):
    serializer_class = AnalysisJobSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={200: AnalysisJobSerializer, 409: AnalysisErrorResponseSerializer})
    def post(self, request, pk):
        job = get_object_or_404(AnalysisJob, pk=pk, owner=request.user)
        if job.status not in (AnalysisJob.Status.QUEUED, AnalysisJob.Status.PROCESSING,
                              AnalysisJob.Status.WAITING_FOR_QUOTA):
            return Response({'detail': 'Only queued or processing analyses can be cancelled.'}, status=409)
        job.status = AnalysisJob.Status.CANCELLED
        job.error_message = 'Analysis cancelled by the account owner.'
        job.save(update_fields=('status', 'error_message', 'updated_at'))
        return Response(AnalysisJobSerializer(job).data)


class AnalysisResumeView(APIView):
    serializer_class = AnalysisJobSerializer
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'ai_analysis'

    @extend_schema(responses={202: AnalysisJobSerializer, 409: AnalysisErrorResponseSerializer,
                              429: AnalysisErrorResponseSerializer, 503: AnalysisJobSerializer})
    def post(self, request, pk):
        with transaction.atomic():
            job = get_object_or_404(AnalysisJob.objects.select_for_update(), pk=pk, owner=request.user)
            if job.status in (AnalysisJob.Status.QUEUED, AnalysisJob.Status.PROCESSING,
                              AnalysisJob.Status.WAITING_FOR_QUOTA):
                return Response(AnalysisJobSerializer(job).data, status=202)
            retryable = AnalysisChunkResult.objects.filter(
                job=job, status=AnalysisChunkResult.Status.FAILED,
                error_category__in=('provider_rate_limit', 'provider_unavailable', 'provider_quota_unavailable'),
            )
            pending = AnalysisChunkResult.objects.filter(job=job, status=AnalysisChunkResult.Status.QUEUED).exists()
            if job.status not in (AnalysisJob.Status.PARTIALLY_COMPLETED, AnalysisJob.Status.FAILED) or (
                not pending and not retryable.exists()
            ):
                return Response({'detail': 'This analysis has no saved work that can be resumed.'}, status=409)
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            active = AnalysisJob.objects.filter(owner=request.user, status__in=(
                AnalysisJob.Status.QUEUED, AnalysisJob.Status.PROCESSING, AnalysisJob.Status.WAITING_FOR_QUOTA,
            )).exclude(pk=job.pk).count()
            if active >= settings.AI_MAX_ACTIVE_JOBS_PER_USER:
                return Response({'detail': 'Another analysis is already queued or processing for this account.'}, status=429)
            retryable.update(status=AnalysisChunkResult.Status.QUEUED, retry_count=0, error_category='')
            job.status = AnalysisJob.Status.QUEUED
            job.completed_at = None
            job.next_attempt_at = None
            job.processing_lease_until = None
            job.error_category = ''
            job.error_message = ''
            job.save(update_fields=('status', 'completed_at', 'next_attempt_at', 'processing_lease_until',
                                   'error_category', 'error_message', 'updated_at'))
        try:
            process_analysis_job.delay(str(job.pk))
        except Exception:
            job.status = AnalysisJob.Status.FAILED
            job.error_category = 'queue_unavailable'
            job.error_message = 'The AI queue is unavailable. Saved analysis work was preserved.'
            job.save(update_fields=('status', 'error_category', 'error_message', 'updated_at'))
            return Response(AnalysisJobSerializer(job).data, status=503)
        return Response(AnalysisJobSerializer(job).data, status=202)


class DocumentAnalysesView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = AnalysisJobSerializer

    def get_queryset(self):
        get_object_or_404(ResearchDocument, pk=self.kwargs['document_id'], owner=self.request.user)
        return owned_jobs(self.request.user).filter(document_id=self.kwargs['document_id'])


class AnalysisReportView(APIView):
    serializer_class = AnalysisReportAcknowledgementSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={200: AnalysisReportAcknowledgementSerializer})
    def post(self, request, pk):
        job = get_object_or_404(AnalysisJob, pk=pk, owner=request.user)
        return Response({'detail': 'Report is generated from persisted analysis results.',
                         'download_url': f'/api/v1/analyses/{job.pk}/report/'}, status=200)

    @extend_schema(responses={
        200: OpenApiResponse(response=OpenApiTypes.BINARY, description='Generated PDF report.'),
        404: AnalysisErrorResponseSerializer,
    })
    def get(self, request, pk):
        job = get_object_or_404(AnalysisJob.objects.select_related('project', 'document', 'document_version'), pk=pk, owner=request.user)
        from apps.intelligence.services.report_builder import build_analysis_report
        payload = build_analysis_report(job)
        return FileResponse(BytesIO(payload), as_attachment=True,
                            filename=f'scholivyn-analysis-{job.pk}.pdf', content_type='application/pdf')


class AnalysisUsageView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = AIUsageSerializer

    def get_queryset(self):
        get_object_or_404(AnalysisJob, pk=self.kwargs['pk'], owner=self.request.user)
        from apps.intelligence.models import AIUsageRecord
        return AIUsageRecord.objects.filter(job_id=self.kwargs['pk'], user=self.request.user)
