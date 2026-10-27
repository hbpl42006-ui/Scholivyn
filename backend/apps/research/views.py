from pathlib import Path
import shutil
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Count, Max
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema

from .models import DocumentVersion, ResearchDocument, ResearchProject
from .permissions import IsProjectOwner
from .serializers import (DocumentMoveSerializer, DocumentStatusSerializer, DocumentUploadSerializer,
                          DocumentMissingSerializer, DocumentReprocessErrorSerializer,
                          ResearchErrorResponseSerializer, DocumentVersionSerializer,
                          ResearchDocumentSerializer, ResearchProjectSerializer)
from .services import EXTRACTION_ALGORITHM, save_private_file, validate_upload
from .tasks import process_document_version
from apps.similarity.retention import collect_deletion_dependencies, delete_dependent_reports, deletion_conflict
from apps.billing.services.entitlements import BillingError, FeatureUnavailable, InsufficientCredits, finalize_usage, reserve_usage


class ProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = ResearchProjectSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return ResearchProject.objects.filter(owner=self.request.user).annotate(document_count=Count('documents', distinct=True))

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ResearchProjectSerializer
    permission_classes = (permissions.IsAuthenticated, IsProjectOwner)

    def get_queryset(self):
        return ResearchProject.objects.filter(owner=self.request.user).annotate(document_count=Count('documents', distinct=True))

    def destroy(self, request, *args, **kwargs):
        project = self.get_object()
        return _delete_research_resource(
            request, project,
            DocumentVersion.objects.filter(document__project=project, document__owner=request.user),
        )


def _delete_research_resource(request, instance, versions):
    confirmed = isinstance(request.data, dict) and request.data.get('delete_dependent_similarity_reports') is True
    try:
        with transaction.atomic():
            dependencies = collect_deletion_dependencies(request.user, versions)
            conflict = deletion_conflict(dependencies, confirmed=confirmed)
            if conflict:
                return Response(conflict, status=status.HTTP_409_CONFLICT)
            delete_dependent_reports(request.user, dependencies)
            instance.delete()
    except ProtectedError:
        # A concurrent or newly introduced protected reference must never turn
        # into a cascade or a 500. The transaction rolls back report deletion.
        return Response({
            'detail': 'This item now has retained records that prevent deletion. No related data was removed; refresh and review its dependencies.',
            'confirmation_required': False,
            'dependent_similarity_reports': [],
        }, status=status.HTTP_409_CONFLICT)
    return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectDocumentsView(generics.ListAPIView):
    serializer_class = ResearchDocumentSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        return ResearchDocument.objects.filter(project__owner=self.request.user, project_id=self.kwargs['project_id']).prefetch_related('versions')


class DocumentUploadView(APIView):
    serializer_class = DocumentUploadSerializer
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        request=DocumentUploadSerializer,
        responses={201: ResearchDocumentSerializer, 400: ResearchErrorResponseSerializer,
                   404: ResearchErrorResponseSerializer, 503: ResearchErrorResponseSerializer},
    )
    def post(self, request, project_id):
        project = get_object_or_404(ResearchProject, id=project_id, owner=request.user)
        upload = request.FILES.get('file')
        if not upload:
            return Response({'file': ['A file is required.']}, status=status.HTTP_400_BAD_REQUEST)
        extension, mime = validate_upload(upload)
        stored_key = save_private_file(upload)
        reservation = None
        try:
            with transaction.atomic():
                document_id = request.data.get('document_id')
                if document_id:
                    document = get_object_or_404(ResearchDocument, id=document_id, project=project, owner=request.user)
                    revision = (document.versions.order_by('-revision_number').values_list('revision_number', flat=True).first() or 0) + 1
                else:
                    document = ResearchDocument.objects.create(project=project, owner=request.user, original_filename=Path(upload.name).name[:255])
                    revision = 1
                version = DocumentVersion.objects.create(document=document, revision_number=revision,
                    original_filename=Path(upload.name).name[:255], file_extension=extension, mime_type=mime,
                    file_size=upload.size, storage_key=stored_key)
                reservation = reserve_usage(request.user, feature='document_storage',
                    idempotency_key=f'document-version:{version.pk}', units=upload.size,
                    reference_type='document_version', reference_id=str(version.pk))
                if reservation:
                    finalize_usage(reservation, event_key=f'document-storage:{version.pk}',
                        units=upload.size, storage_bytes=upload.size)
        except FeatureUnavailable as exc:
            (Path(settings.PRIVATE_DOCUMENT_ROOT) / stored_key).unlink(missing_ok=True)
            return Response({'detail': str(exc), 'code': 'feature_unavailable'}, status=403)
        except InsufficientCredits as exc:
            (Path(settings.PRIVATE_DOCUMENT_ROOT) / stored_key).unlink(missing_ok=True)
            return Response({'detail': str(exc), 'code': 'insufficient_credits'}, status=402)
        except BillingError as exc:
            (Path(settings.PRIVATE_DOCUMENT_ROOT) / stored_key).unlink(missing_ok=True)
            return Response({'detail': str(exc), 'code': 'billing_error'}, status=409)
        except Exception:
            (Path(settings.PRIVATE_DOCUMENT_ROOT) / stored_key).unlink(missing_ok=True)
            raise
        try:
            process_document_version.delay(str(version.pk))
        except Exception:
            version.processing_status = DocumentVersion.ProcessingStatus.PENDING
            version.processing_error = 'The processing queue is unavailable. This upload is saved; retry extraction when the worker is available.'
            version.save(update_fields=('processing_status', 'processing_error'))
        return Response(ResearchDocumentSerializer(document).data, status=status.HTTP_201_CREATED)


def owned_document(request, document_id):
    return get_object_or_404(ResearchDocument.objects.prefetch_related('versions'), id=document_id, owner=request.user)


class DocumentDetailView(APIView):
    serializer_class = ResearchDocumentSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=ResearchDocumentSerializer)
    def get(self, request, document_id):
        return Response(ResearchDocumentSerializer(owned_document(request, document_id)).data)

    @extend_schema(request=DocumentMoveSerializer, responses={200: ResearchDocumentSerializer, 400: ResearchErrorResponseSerializer})
    def patch(self, request, document_id):
        document = owned_document(request, document_id)
        project_id = request.data.get('project')
        if not project_id:
            return Response({'project': ['Choose a project owned by your account.']}, status=400)
        project = get_object_or_404(ResearchProject, id=project_id, owner=request.user)
        document.project = project
        document.save(update_fields=('project', 'updated_at'))
        return Response(ResearchDocumentSerializer(document).data)

    @extend_schema(responses={204: OpenApiResponse(description='Document deleted.')})
    def delete(self, request, document_id):
        document = owned_document(request, document_id)
        return _delete_research_resource(
            request, document, DocumentVersion.objects.filter(document=document),
        )


class DocumentVersionsView(APIView):
    serializer_class = DocumentVersionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses=DocumentVersionSerializer(many=True))
    def get(self, request, document_id):
        document = owned_document(request, document_id)
        return Response(DocumentVersionSerializer(document.versions.all(), many=True).data)


class DocumentReprocessView(APIView):
    serializer_class = DocumentVersionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={
        200: DocumentVersionSerializer, 202: DocumentVersionSerializer,
        404: ResearchErrorResponseSerializer, 409: ResearchErrorResponseSerializer,
        503: DocumentReprocessErrorSerializer,
    })
    def post(self, request, document_id, version_id):
        document = get_object_or_404(ResearchDocument, pk=document_id, owner=request.user)
        source = get_object_or_404(DocumentVersion, pk=version_id, document=document)
        if source.processing_status in (DocumentVersion.ProcessingStatus.PENDING, DocumentVersion.ProcessingStatus.PROCESSING):
            return Response({'detail': 'Wait for the current extraction to finish before reprocessing.'}, status=409)
        existing = DocumentVersion.objects.filter(reprocessed_from=source, extraction_algorithm=EXTRACTION_ALGORITHM).first()
        if existing:
            return self._queue_if_retryable(existing)
        source_path = Path(settings.PRIVATE_DOCUMENT_ROOT) / source.storage_key
        if not source_path.is_file():
            return Response({'detail': 'The private source file is unavailable; reprocessing cannot continue.'}, status=404)
        stored_key = f'{uuid.uuid4().hex}{source.file_extension.lower()}'
        destination = Path(settings.PRIVATE_DOCUMENT_ROOT) / stored_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, destination)
        try:
            with transaction.atomic():
                ResearchDocument.objects.select_for_update().get(pk=document.pk)
                revision = (document.versions.aggregate(value=Max('revision_number'))['value'] or 0) + 1
                candidate = DocumentVersion.objects.create(
                    document=document, revision_number=revision, original_filename=source.original_filename,
                    file_extension=source.file_extension, mime_type=source.mime_type, file_size=source.file_size,
                    storage_key=stored_key, extraction_algorithm=EXTRACTION_ALGORITHM,
                    reprocessed_from=source, processing_status=DocumentVersion.ProcessingStatus.PENDING)
        except IntegrityError:
            destination.unlink(missing_ok=True)
            candidate = DocumentVersion.objects.get(reprocessed_from=source, extraction_algorithm=EXTRACTION_ALGORITHM)
            return self._queue_if_retryable(candidate)
        return self._queue_if_retryable(candidate)

    @staticmethod
    def _queue_if_retryable(version):
        if version.processing_status == DocumentVersion.ProcessingStatus.COMPLETED:
            return Response(DocumentVersionSerializer(version).data, status=200)
        if version.processing_status == DocumentVersion.ProcessingStatus.PROCESSING:
            return Response(DocumentVersionSerializer(version).data, status=202)
        version.processing_status = DocumentVersion.ProcessingStatus.PENDING
        version.processing_started_at = None
        version.processing_error = ''
        version.extraction_metadata = {}
        version.save(update_fields=('processing_status', 'processing_started_at', 'processing_error', 'extraction_metadata'))
        try:
            process_document_version.delay(str(version.pk))
        except Exception:
            version.processing_error = 'The processing queue is unavailable. The version is saved; retry extraction when the worker is available.'
            DocumentVersion.objects.filter(pk=version.pk, processing_status=DocumentVersion.ProcessingStatus.PENDING).update(
                processing_error=version.processing_error)
            version.refresh_from_db()
            return Response({'detail': version.processing_error, 'version': DocumentVersionSerializer(version).data}, status=503)
        return Response(DocumentVersionSerializer(version).data, status=202)


class DocumentRetryExtractionView(APIView):
    serializer_class = DocumentVersionSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={200: DocumentVersionSerializer, 202: DocumentVersionSerializer,
                              404: ResearchErrorResponseSerializer, 409: ResearchErrorResponseSerializer,
                              503: DocumentReprocessErrorSerializer})
    def post(self, request, document_id, version_id):
        document = get_object_or_404(ResearchDocument, pk=document_id, owner=request.user)
        with transaction.atomic():
            version = get_object_or_404(DocumentVersion.objects.select_for_update(), pk=version_id, document=document)
            if version.processing_status == DocumentVersion.ProcessingStatus.COMPLETED:
                return Response(DocumentVersionSerializer(version).data, status=200)
            now = timezone.now()
            if version.processing_status == DocumentVersion.ProcessingStatus.PROCESSING:
                started_at = version.processing_started_at or version.uploaded_at
                stale_after = timedelta(seconds=settings.DOCUMENT_PROCESSING_STALE_SECONDS)
                if now - started_at < stale_after:
                    return Response({'detail': 'Extraction is currently processing. Retry is available after the stuck-task timeout.'}, status=409)
            elif version.processing_status not in (DocumentVersion.ProcessingStatus.PENDING,
                                                     DocumentVersion.ProcessingStatus.FAILED):
                return Response({'detail': 'This document version cannot be retried in its current state.'}, status=409)

            old_status = version.processing_status
            changed = DocumentVersion.objects.filter(pk=version.pk, processing_status=old_status).update(
                processing_status=DocumentVersion.ProcessingStatus.PENDING, processing_started_at=None,
                processing_error='', extraction_metadata={})
            if not changed:
                version.refresh_from_db()
                return Response(DocumentVersionSerializer(version).data, status=202)
            version.refresh_from_db()

        try:
            process_document_version.delay(str(version.pk))
        except Exception:
            message = 'The processing queue is unavailable. The version is saved; retry extraction when the worker is available.'
            DocumentVersion.objects.filter(pk=version.pk, processing_status=DocumentVersion.ProcessingStatus.PENDING).update(
                processing_error=message)
            version.refresh_from_db()
            return Response({'detail': message, 'version': DocumentVersionSerializer(version).data}, status=503)
        version.refresh_from_db()
        return Response(DocumentVersionSerializer(version).data, status=202)


class DocumentStatusView(APIView):
    serializer_class = DocumentStatusSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={200: DocumentStatusSerializer, 404: DocumentMissingSerializer})
    def get(self, request, document_id):
        document = owned_document(request, document_id)
        version = document.current_version
        if not version:
            return Response({'status': 'missing'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'document_id': str(document.id), 'version_id': str(version.id),
                         'status': version.processing_status, 'processing_error': version.processing_error,
                         'uploaded_at': version.uploaded_at,
                         'extraction_metadata': version.extraction_metadata})


class DocumentFileView(APIView):
    serializer_class = ResearchErrorResponseSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(responses={
        200: OpenApiResponse(response=OpenApiTypes.BINARY, description='Private source document bytes.'),
        404: ResearchErrorResponseSerializer,
    })
    def get(self, request, document_id):
        document = owned_document(request, document_id)
        version_id = request.query_params.get('version')
        version = get_object_or_404(document.versions.all(), pk=version_id) if version_id else document.current_version
        if not version:
            return Response({'detail': 'Document version not found.'}, status=404)
        path = Path(settings.PRIVATE_DOCUMENT_ROOT) / version.storage_key
        if not path.is_file():
            return Response({'detail': 'The private document file is no longer available.'}, status=404)
        return FileResponse(open(path, 'rb'),
                            content_type=version.mime_type, as_attachment=False, filename=version.original_filename)
