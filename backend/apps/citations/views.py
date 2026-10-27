from io import BytesIO
import logging
from xml.sax.saxutils import escape

from django.conf import settings
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
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from .models import (BibliographicReference, CitationAnalysisJob, CitationFinding, CitationReviewDecision,
                     CitationMatch, ExtractedCitation)
from .serializers import (BibliographicReferenceSerializer, CitationAnalysisCreateSerializer,
    CitationAnalysisJobSerializer, CitationDecisionInputSerializer, CitationFindingSerializer,
    CitationMatchSerializer, CitationReviewDecisionSerializer, ExtractedCitationSerializer)
from .tasks import process_citation_analysis, verify_citation_metadata
from apps.billing.services.entitlements import BillingError, reserve_usage, release_reservation
from apps.billing.services.usage import billing_http_status

logger = logging.getLogger(__name__)


def _enqueue(task, job):
    try:
        task.apply_async(args=(str(job.pk),), queue='celery')
    except Exception as exc:
        logger.warning('Citation task enqueue failed type=%s', type(exc).__name__,
                       extra={'citation_job_id': str(job.pk), 'error_category': 'queue_unavailable'})
        reservation = __import__('apps.billing.models', fromlist=['CreditReservation']).CreditReservation.objects.filter(
            reference_type='citation_job', reference_id=str(job.pk)).first()
        release_reservation(reservation)
        if getattr(task, 'name', '').endswith('verify_citation_metadata'):
            job.metadata_status = 'failed'
            job.save(update_fields=('metadata_status','updated_at'))
        else:
            job.status = CitationAnalysisJob.Status.FAILED
            job.error_category = 'queue_unavailable'
            job.error_message = 'The citation worker is unavailable. Check the worker and retry.'
            job.save(update_fields=('status','error_category','error_message','updated_at'))


def _owned_job(request, job_id):
    return get_object_or_404(CitationAnalysisJob.objects.select_related(
        'document_version__document__project'), pk=job_id, owner=request.user)


class CitationPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 100


class CitationAnalysisListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    pagination_class = CitationPagination

    @extend_schema(responses=CitationAnalysisJobSerializer(many=True))
    def get(self, request):
        queryset = CitationAnalysisJob.objects.filter(owner=request.user).select_related('document_version__document__project')
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(CitationAnalysisJobSerializer(page, many=True).data)

    @extend_schema(request=CitationAnalysisCreateSerializer, responses={201:CitationAnalysisJobSerializer, 200:CitationAnalysisJobSerializer, 400:OpenApiResponse(description='Invalid document/version or options.')})
    def post(self, request):
        serializer = CitationAnalysisCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data, version = serializer.validated_data, serializer.context['version']
        job, created = None, False
        try:
            with transaction.atomic():
                job, created = CitationAnalysisJob.objects.get_or_create(owner=request.user,
                    client_request_id=data['client_request_id'], defaults={
                        'document_version': version, 'citation_style': data['citation_style'],
                        'metadata_consent': data['metadata_consent'],
                    })
                if not created and (job.document_version_id != version.pk or job.citation_style != data['citation_style']
                                    or job.metadata_consent != data['metadata_consent']):
                    return Response({'detail':'This idempotency key was already used for a different citation request.'}, status=409)
                if created:
                    reserve_usage(request.user, feature='citation_analysis',
                        idempotency_key=f"citation:{data['client_request_id']}", units=1,
                        reference_type='citation_job', reference_id=str(job.pk))
                    transaction.on_commit(lambda: _enqueue(process_citation_analysis, job))
        except IntegrityError:
            job = CitationAnalysisJob.objects.get(owner=request.user, client_request_id=data['client_request_id'])
        except BillingError as exc:
            return Response({'detail': str(exc), 'code': 'billing_error'}, status=billing_http_status(exc))
        return Response(CitationAnalysisJobSerializer(job).data, status=201 if created else 200)


class CitationAnalysisDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=CitationAnalysisJobSerializer)
    def get(self, request, job_id):
        return Response(CitationAnalysisJobSerializer(_owned_job(request, job_id)).data)

    @extend_schema(responses={204:OpenApiResponse(description='Citation analysis and derived results deleted.'),404:OpenApiResponse(description='Analysis not found.')})
    def delete(self, request, job_id):
        _owned_job(request, job_id).delete()
        return Response(status=204)


class CitationItemsView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    pagination_class = CitationPagination

    @extend_schema(responses=OpenApiResponse(description='Paginated citations, references, matches, or findings.'))
    def get(self, request, job_id):
        job = _owned_job(request, job_id)
        kind = request.query_params.get('kind', 'findings')
        options = {
            'citations': (job.citations.all(), ExtractedCitationSerializer),
            'references': (job.references.prefetch_related('metadata_checks','matches','findings'), BibliographicReferenceSerializer),
            'matches': (job.matches.select_related('citation','reference'), CitationMatchSerializer),
            'findings': (job.findings.select_related('citation','reference').prefetch_related('review_decision'), CitationFindingSerializer),
        }
        if kind not in options:
            return Response({'kind':['Choose citations, references, matches, or findings.']}, status=400)
        queryset, item_serializer = options[kind]
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(item_serializer(page, many=True).data)


class CitationActionView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200:CitationAnalysisJobSerializer,409:OpenApiResponse(description='Action not available for current status.')})
    def post(self, request, job_id, action):
        job = _owned_job(request, job_id)
        if action == 'cancel':
            updated = CitationAnalysisJob.objects.filter(pk=job.pk, owner=request.user,
                status__in=(CitationAnalysisJob.Status.QUEUED,CitationAnalysisJob.Status.PROCESSING)).update(
                status=CitationAnalysisJob.Status.CANCELLED, completed_at=timezone.now(), lease_until=None)
            if not updated:
                return Response({'detail':'Only queued or processing citation jobs can be cancelled.'}, status=409)
        elif action == 'retry':
            updated = CitationAnalysisJob.objects.filter(pk=job.pk, owner=request.user,
                status=CitationAnalysisJob.Status.FAILED).update(status=CitationAnalysisJob.Status.QUEUED,
                error_category='', error_message='', completed_at=None, lease_until=None, progress=0)
            if not updated:
                return Response({'detail':'Only failed citation jobs can be retried.'}, status=409)
            transaction.on_commit(lambda: _enqueue(process_citation_analysis, job))
        elif action == 'verify-metadata':
            if request.data.get('consent') is not True:
                return Response({'consent':['Explicit consent is required before sending DOI/title metadata to providers.']}, status=400)
            if job.status != CitationAnalysisJob.Status.COMPLETED:
                return Response({'detail':'Complete citation extraction before metadata verification.'}, status=409)
            if not settings.CITATION_METADATA_ENABLED:
                return Response({'detail':'Metadata lookups are disabled by the workspace administrator.'}, status=503)
            CitationAnalysisJob.objects.filter(pk=job.pk, owner=request.user).update(metadata_consent=True, metadata_status='queued')
            transaction.on_commit(lambda: _enqueue(verify_citation_metadata, job))
        else:
            return Response({'detail':'Unknown citation action.'}, status=404)
        return Response(CitationAnalysisJobSerializer(_owned_job(request, job.pk)).data)


class CitationReviewDecisionView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(request=CitationDecisionInputSerializer, responses={200:CitationReviewDecisionSerializer,404:OpenApiResponse(description='Finding not found.')})
    def post(self, request, job_id, finding_id):
        job = _owned_job(request, job_id)
        finding = get_object_or_404(CitationFinding, pk=finding_id, job=job, job__owner=request.user)
        serializer = CitationDecisionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision, _ = CitationReviewDecision.objects.update_or_create(finding=finding, defaults={
            'owner': request.user, **serializer.validated_data})
        return Response(CitationReviewDecisionSerializer(decision).data)


class CitationReportView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={200:OpenApiResponse(response=OpenApiTypes.BINARY, description='Version-pinned citation verification PDF.'),404:OpenApiResponse(description='Analysis not found.')})
    def get(self, request, job_id):
        job = _owned_job(request, job_id)
        if job.status != CitationAnalysisJob.Status.COMPLETED:
            return Response({'detail':'The citation report is available after analysis completes.'}, status=409)
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=.65*inch, leftMargin=.65*inch,
            topMargin=.65*inch, bottomMargin=.65*inch, title='Scholivyn citation verification', author='Scholivyn')
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='CitationEvidence', parent=styles['BodyText'], fontSize=8, leading=11))
        story = [Paragraph('Scholivyn — Citation and reference check', styles['Title']),
            Paragraph(f'Manuscript: {escape(job.document_version.original_filename)} · revision {job.document_version.revision_number}', styles['BodyText']),
            Paragraph(f'Project: {escape(job.document_version.document.project.title)} · style: {escape(job.citation_style)}', styles['BodyText']),
            Paragraph(f'{job.citation_count} citations · {job.reference_count} references · {job.matched_count} matched · {job.unmatched_count} unmatched · {job.ambiguous_count} ambiguous', styles['BodyText']),
            Spacer(1, 10), Paragraph('Interpretation', styles['Heading2']),
            Paragraph('These deterministic checks identify structural inconsistencies and metadata candidates. They do not establish fabrication, misconduct, source quality, or intent. No citation authenticity score is computed.', styles['BodyText'])]
        for finding in job.findings.select_related('citation','reference').prefetch_related('review_decision'):
            evidence = finding.citation.raw_text if finding.citation_id else finding.reference.raw_text[:600] if finding.reference_id else ''
            story.extend((Spacer(1, 7), Paragraph(f'{escape(finding.get_severity_display())}: {escape(finding.code)}', styles['Heading3']),
                Paragraph(escape(finding.explanation), styles['BodyText']),
                Paragraph(f'Evidence: {escape(evidence)}', styles['CitationEvidence']) if evidence else Spacer(1, 1)))
        for reference in job.references.prefetch_related('metadata_checks').all():
            for check in reference.metadata_checks.all():
                if check.status in ('mismatch','ambiguous','matched'):
                    story.extend((Spacer(1, 6), Paragraph(f'{escape(check.provider)} metadata · {escape(check.status)}', styles['Heading3']),
                        Paragraph(escape(reference.raw_text[:600]), styles['CitationEvidence']),
                        Paragraph(escape(str(check.metadata.get('explanation') or 'Registry metadata candidate attached.')), styles['BodyText'])))
        doc.build(story); buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename=f'scholivyn-citations-{job.pk}.pdf', content_type='application/pdf')
