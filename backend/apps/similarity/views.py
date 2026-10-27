from io import BytesIO
import logging
from xml.sax.saxutils import escape

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.research.models import DocumentVersion
from apps.billing.services.entitlements import BillingError, release_reservation, reserve_usage
from apps.billing.services.usage import billing_http_status
from .models import SimilarityComparison, SimilarityJob
from .serializers import SimilarityCreateSerializer, SimilarityJobSerializer, SimilarityMatchSerializer
from .tasks import process_similarity_job

logger = logging.getLogger(__name__)


def _enqueue_job(job_id):
    try:
        process_similarity_job.delay(str(job_id))
    except Exception as exc:
        logger.warning('Similarity task could not be queued (%s).', type(exc).__name__,
                       extra={'similarity_job_id': str(job_id), 'error_category': 'queue_unavailable'})
        SimilarityJob.objects.filter(pk=job_id, status=SimilarityJob.Status.QUEUED).update(
            status=SimilarityJob.Status.FAILED,
            error_message='The similarity worker is unavailable. Check the worker and retry this comparison.',
            completed_at=timezone.now())
        reservation = __import__('apps.billing.models', fromlist=['CreditReservation']).CreditReservation.objects.filter(
            reference_type='similarity_job', reference_id=str(job_id)).first()
        release_reservation(reservation)

class SimilarityListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=SimilarityJobSerializer(many=True))
    def get(self, request):
        jobs = SimilarityJob.objects.filter(owner=request.user).select_related(
            'source_version__document__project').prefetch_related(
            'comparisons__target_version__document__project', 'comparisons__matches')[:100]
        return Response(SimilarityJobSerializer(jobs, many=True).data)

    @extend_schema(request=SimilarityCreateSerializer, responses={201: SimilarityJobSerializer, 400: OpenApiResponse(description='Invalid selection.'), 404: OpenApiResponse(description='Selected version not found.')})
    def post(self, request):
        serializer = SimilarityCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if len(data['target_version_ids']) > settings.SIMILARITY_MAX_TARGET_VERSIONS:
            return Response({'target_version_ids': [f'Compare at most {settings.SIMILARITY_MAX_TARGET_VERSIONS} target versions at once.']}, status=400)
        ids = [data['source_version_id'], *data['target_version_ids']]
        versions = {item.id: item for item in DocumentVersion.objects.select_related('document__project').filter(
            id__in=ids, document__owner=request.user, document__project__owner=request.user)}
        if len(versions) != len(set(ids)):
            return Response({'detail': 'One or more selected versions are unavailable in your workspace.'}, status=404)
        source = versions[data['source_version_id']]
        if source.processing_status != DocumentVersion.ProcessingStatus.COMPLETED:
            return Response({'detail': 'The source version must finish extraction before comparison.'}, status=400)
        if source.id in data['target_version_ids']:
            return Response({'target_version_ids': ['The source version cannot also be a target.']}, status=400)
        pending = [version for version_id in data['target_version_ids'] for version in [versions[version_id]]
                   if version.processing_status != DocumentVersion.ProcessingStatus.COMPLETED]
        if pending:
            return Response({'detail': 'Every selected target version must finish extraction before comparison.'}, status=400)
        created = False
        try:
            with transaction.atomic():
                job, created = SimilarityJob.objects.get_or_create(
                    owner=request.user, client_request_id=data['client_request_id'], defaults={
                        'source_version': source, 'min_passage_words': settings.SIMILARITY_MIN_PASSAGE_WORDS,
                        'near_threshold': settings.SIMILARITY_NEAR_THRESHOLD,
                        'shingle_size': settings.SIMILARITY_SHINGLE_SIZE,
                        'total_targets': len(data['target_version_ids']),
                    })
                if created:
                    SimilarityComparison.objects.bulk_create([
                        SimilarityComparison(job=job, target_version=versions[version_id])
                        for version_id in data['target_version_ids']])
                    reserve_usage(request.user, feature='similarity_comparison',
                        idempotency_key=f"similarity:{data['client_request_id']}",
                        units=len(data['target_version_ids']), reference_type='similarity_job', reference_id=str(job.pk))
                    transaction.on_commit(lambda: _enqueue_job(job.pk))
                elif job.source_version_id != source.id or set(job.comparisons.values_list('target_version_id', flat=True)) != set(data['target_version_ids']):
                    return Response({'client_request_id': ['This idempotency key was already used for another comparison.']}, status=409)
        except IntegrityError:
            job = SimilarityJob.objects.get(owner=request.user, client_request_id=data['client_request_id'])
        except BillingError as exc:
            return Response({'detail': str(exc), 'code': 'billing_error'}, status=billing_http_status(exc))
        return Response(SimilarityJobSerializer(job).data, status=201 if created else 200)


def _owned_job(request, job_id):
    return get_object_or_404(SimilarityJob.objects.select_related(
        'source_version__document__project').prefetch_related(
        'comparisons__target_version__document__project', 'comparisons__matches'),
        pk=job_id, owner=request.user)


class SimilarityDetailView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=SimilarityJobSerializer)
    def get(self, request, job_id):
        return Response(SimilarityJobSerializer(_owned_job(request, job_id)).data)

    @extend_schema(responses={204: OpenApiResponse(description='Similarity report and its comparison results deleted.'), 404: OpenApiResponse(description='Report not found.')})
    def delete(self, request, job_id):
        job = _owned_job(request, job_id)
        job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SimilarityActionView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={200: SimilarityJobSerializer, 409: OpenApiResponse(description='Job is not eligible for this action.')})
    def post(self, request, job_id, action):
        job = _owned_job(request, job_id)
        if action == 'cancel':
            updated = SimilarityJob.objects.filter(pk=job.pk, owner=request.user,
                status__in=(SimilarityJob.Status.QUEUED, SimilarityJob.Status.PROCESSING)).update(
                status=SimilarityJob.Status.CANCELLED, completed_at=timezone.now(), lease_until=None)
            if not updated:
                return Response({'detail': 'Only queued or processing comparisons can be cancelled.'}, status=409)
        elif action == 'retry':
            updated = SimilarityJob.objects.filter(pk=job.pk, owner=request.user,
                status=SimilarityJob.Status.FAILED).update(status=SimilarityJob.Status.QUEUED,
                error_message='', completed_at=None, lease_until=None)
            if not updated:
                return Response({'detail': 'Only failed comparisons can be retried.'}, status=409)
            transaction.on_commit(lambda: _enqueue_job(job.pk))
        return Response(SimilarityJobSerializer(_owned_job(request, job.pk)).data)


class SimilarityReportView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={200: OpenApiResponse(response=OpenApiTypes.BINARY, description='Selected-source similarity PDF report.'), 404: OpenApiResponse(description='Report not found.')})
    def get(self, request, job_id):
        job = _owned_job(request, job_id)
        if job.status != SimilarityJob.Status.COMPLETED:
            return Response({'detail': 'The similarity report is available after processing completes.'}, status=409)
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=.65*inch, leftMargin=.65*inch,
                                topMargin=.65*inch, bottomMargin=.65*inch, title='Scholivyn similarity report', author='Scholivyn')
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='MatchText', parent=styles['BodyText'], fontSize=8, leading=11,
                                  backColor=colors.HexColor('#f1f5f9'), borderPadding=6))
        story = [Paragraph('Scholivyn — Selected-source similarity report', styles['Title']),
                 Paragraph(f'Source: {escape(job.source_version.original_filename)} (revision {job.source_version.revision_number})', styles['BodyText']),
                 Paragraph(f'Project: {escape(job.source_version.document.project.title)}', styles['BodyText']),
                 Paragraph(f'Corpus scope: {job.total_targets} explicitly selected, accessible manuscript version(s). No external database or web coverage.', styles['BodyText']),
                 Paragraph(f'Matched source text: {job.matched_percentage:.2f}% ({job.matched_source_words:,} of {job.source_word_count:,} non-reference words). Exact passages: {job.exact_match_count}; near-duplicate passages: {job.near_match_count}.', styles['BodyText']),
                 Spacer(1, 10), Paragraph('Interpretation', styles['Heading2']),
                 Paragraph('Similarity is not proof of plagiarism, intent, or misconduct. Citations and quotations may be legitimate. This report only compares the versions explicitly selected by the user; it is not equivalent to Turnitin and does not search external scholarly or internet sources.', styles['BodyText'])]
        for comparison in job.comparisons.select_related('target_version__document__project').prefetch_related('matches'):
            story.extend([Spacer(1, 10), Paragraph(f'Compared with: {escape(comparison.target_version.original_filename)} (revision {comparison.target_version.revision_number}) — {escape(comparison.target_version.document.project.title)}', styles['Heading2'])])
            for match in comparison.matches.all():
                row = SimilarityMatchSerializer(match)
                source_text = row.data['source_text']
                target_text = row.data['target_text']
                story.append(Paragraph(f'{escape(match.get_match_type_display())} · {match.similarity:.0%} · {escape(match.citation_label.replace("_", " "))}', styles['Heading3']))
                story.append(Paragraph(f'Source {escape(match.source_section_title)} · paragraph {match.source_paragraph_index + 1}: {escape(source_text)}', styles['MatchText']))
                story.append(Paragraph(f'Target {escape(match.target_section_title)} · paragraph {match.target_paragraph_index + 1}: {escape(target_text)}', styles['MatchText']))
        doc.build(story)
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename=f'scholivyn-similarity-{job.pk}.pdf', content_type='application/pdf')
