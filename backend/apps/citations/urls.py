from django.urls import path

from .views import (CitationActionView, CitationAnalysisDetailView, CitationAnalysisListCreateView,
                    CitationItemsView, CitationReportView, CitationReviewDecisionView)

urlpatterns = [
    path('citations/jobs/', CitationAnalysisListCreateView.as_view(), name='citation-job-list-create'),
    path('citations/jobs/<uuid:job_id>/', CitationAnalysisDetailView.as_view(), name='citation-job-detail'),
    path('citations/jobs/<uuid:job_id>/items/', CitationItemsView.as_view(), name='citation-job-items'),
    path('citations/jobs/<uuid:job_id>/actions/<str:action>/', CitationActionView.as_view(), name='citation-job-action'),
    path('citations/jobs/<uuid:job_id>/findings/<int:finding_id>/decision/', CitationReviewDecisionView.as_view(), name='citation-finding-decision'),
    path('citations/jobs/<uuid:job_id>/report/', CitationReportView.as_view(), name='citation-job-report'),
]
