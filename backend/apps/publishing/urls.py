from django.urls import path

from .views import (ProfileDetailView, ProfileListCreateView, ReadinessListCreateView,
    ReadinessReportView, RecommendationActionView, RecommendationDetailView,
    RecommendationListCreateView, SavedJournalDetailView, SavedJournalListCreateView,
    SubmissionPreparationView)

urlpatterns = [
    path('publishing/profiles/', ProfileListCreateView.as_view(), name='publishing-profiles'),
    path('publishing/profiles/<int:profile_id>/', ProfileDetailView.as_view(), name='publishing-profile-detail'),
    path('publishing/recommendations/', RecommendationListCreateView.as_view(), name='journal-recommendations'),
    path('publishing/recommendations/<uuid:job_id>/', RecommendationDetailView.as_view(), name='journal-recommendation-detail'),
    path('publishing/recommendations/<uuid:job_id>/actions/<str:action>/', RecommendationActionView.as_view(), name='journal-recommendation-action'),
    path('publishing/saved-journals/', SavedJournalListCreateView.as_view(), name='saved-journals'),
    path('publishing/saved-journals/<int:saved_id>/', SavedJournalDetailView.as_view(), name='saved-journal-detail'),
    path('publishing/readiness/', ReadinessListCreateView.as_view(), name='publication-readiness'),
    path('publishing/readiness/<int:assessment_id>/report/', ReadinessReportView.as_view(), name='publication-readiness-report'),
    path('publishing/submissions/', SubmissionPreparationView.as_view(), name='submission-preparation'),
]
