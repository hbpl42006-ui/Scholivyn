from django.urls import path

from .views import (DocumentDetailView, DocumentFileView, DocumentReprocessView, DocumentRetryExtractionView, DocumentStatusView, DocumentUploadView,
                    DocumentVersionsView, ProjectDetailView, ProjectDocumentsView, ProjectListCreateView)

urlpatterns = [
    path('projects/', ProjectListCreateView.as_view(), name='project-list'),
    path('projects/<uuid:pk>/', ProjectDetailView.as_view(), name='project-detail'),
    path('projects/<uuid:project_id>/documents/', ProjectDocumentsView.as_view(), name='project-documents'),
    path('projects/<uuid:project_id>/documents/upload/', DocumentUploadView.as_view(), name='document-upload'),
    path('documents/<uuid:document_id>/', DocumentDetailView.as_view(), name='document-detail'),
    path('documents/<uuid:document_id>/status/', DocumentStatusView.as_view(), name='document-status'),
    path('documents/<uuid:document_id>/versions/', DocumentVersionsView.as_view(), name='document-versions'),
    path('documents/<uuid:document_id>/versions/<uuid:version_id>/reprocess/', DocumentReprocessView.as_view(), name='document-reprocess'),
    path('documents/<uuid:document_id>/versions/<uuid:version_id>/retry-extraction/', DocumentRetryExtractionView.as_view(), name='document-retry-extraction'),
    path('documents/<uuid:document_id>/file/', DocumentFileView.as_view(), name='document-file'),
]
