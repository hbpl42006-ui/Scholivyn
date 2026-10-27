from django.urls import path

from .views import SimilarityActionView, SimilarityDetailView, SimilarityListCreateView, SimilarityReportView

urlpatterns = [
    path('similarity/', SimilarityListCreateView.as_view(), name='similarity-list-create'),
    path('similarity/<uuid:job_id>/', SimilarityDetailView.as_view(), name='similarity-detail'),
    path('similarity/<uuid:job_id>/report/', SimilarityReportView.as_view(), name='similarity-report'),
    path('similarity/<uuid:job_id>/<str:action>/', SimilarityActionView.as_view(), name='similarity-action'),
]
