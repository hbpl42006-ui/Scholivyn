from django.urls import path

from .views import (AnalysisCancelView, AnalysisDetailView, AnalysisIssueUpdateView,
                    AnalysisIssuesView, AnalysisListCreateView, AnalysisReportView,
                    AnalysisResumeView, AnalysisSectionsView, AnalysisStatusView, AnalysisUsageView,
                    DocumentAnalysesView)

urlpatterns = [
    path('analyses/', AnalysisListCreateView.as_view(), name='analysis-list-create'),
    path('analyses/<uuid:pk>/', AnalysisDetailView.as_view(), name='analysis-detail'),
    path('analyses/<uuid:pk>/status/', AnalysisStatusView.as_view(), name='analysis-status'),
    path('analyses/<uuid:pk>/sections/', AnalysisSectionsView.as_view(), name='analysis-sections'),
    path('analyses/<uuid:pk>/issues/', AnalysisIssuesView.as_view(), name='analysis-issues'),
    path('analyses/<uuid:pk>/cancel/', AnalysisCancelView.as_view(), name='analysis-cancel'),
    path('analyses/<uuid:pk>/resume/', AnalysisResumeView.as_view(), name='analysis-resume'),
    path('analyses/<uuid:pk>/report/', AnalysisReportView.as_view(), name='analysis-report'),
    path('analyses/<uuid:pk>/usage/', AnalysisUsageView.as_view(), name='analysis-usage'),
    path('analyses/issues/<uuid:issue_id>/', AnalysisIssueUpdateView.as_view(), name='analysis-issue-update'),
    path('documents/<uuid:document_id>/analyses/', DocumentAnalysesView.as_view(), name='document-analyses'),
]
