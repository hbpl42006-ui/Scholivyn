from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from apps.accounts.views import health
urlpatterns = [path('admin/', admin.site.urls), path('api/v1/', include('apps.accounts.urls')), path('api/v1/', include('apps.research.urls')), path('api/v1/', include('apps.intelligence.urls')), path('api/v1/', include('apps.similarity.urls')), path('api/v1/', include('apps.citations.urls')), path('api/v1/', include('apps.publishing.urls')), path('api/v1/', include('apps.billing.urls')), path('api/schema/', SpectacularAPIView.as_view(), name='schema'), path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema')), path('health/', health)]
