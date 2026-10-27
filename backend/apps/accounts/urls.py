from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (MeView, PasswordResetConfirmView, PasswordResetRequestView,
                    RegisterView, VerifyEmailView, ResendVerificationView,
                    ChangeVerificationEmailView, LoginView)
urlpatterns=[path('auth/register/',RegisterView.as_view()),path('auth/login/',LoginView.as_view()),path('auth/refresh/',TokenRefreshView.as_view()),path('auth/me/',MeView.as_view()),path('auth/verify-email/',VerifyEmailView.as_view()),path('auth/verify-email/resend/',ResendVerificationView.as_view()),path('auth/verify-email/change-email/',ChangeVerificationEmailView.as_view()),path('auth/password-reset/',PasswordResetRequestView.as_view()),path('auth/password-reset/confirm/',PasswordResetConfirmView.as_view())]
