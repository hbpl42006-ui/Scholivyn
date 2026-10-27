from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from urllib.parse import urlencode
from django.http import JsonResponse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import base36_to_int, urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from drf_spectacular.utils import extend_schema
from .serializers import (EmailVerificationSerializer, PasswordResetConfirmSerializer,
                          PasswordResetRequestSerializer, RegisterSerializer, UserSerializer,
                          ResendVerificationSerializer, ChangeVerificationEmailSerializer,
                          ActionMessageSerializer, ErrorResponseSerializer)
from .serializers import EmailOrUsernameTokenSerializer
from .throttles import VerificationEmailThrottle, VerificationIPThrottle
User=get_user_model()
class LoginView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenSerializer

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    def perform_create(self, serializer):
        user = serializer.save(is_active=False)
        _send_verification_email(user)

class VerifyEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [VerificationIPThrottle]
    @extend_schema(request=EmailVerificationSerializer, responses={200: ActionMessageSerializer, 400: ErrorResponseSerializer})
    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user_id = force_str(urlsafe_base64_decode(serializer.validated_data['uid']))
            user = User.objects.get(pk=user_id)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            return Response({'detail': 'This verification link is invalid or expired.'}, status=status.HTTP_400_BAD_REQUEST)
        if not default_token_generator.check_token(user, serializer.validated_data['token']):
            token = serializer.validated_data['token']
            try:
                timestamp_text, separator, signature = token.partition('-')
                is_well_formed = separator and len(signature) == 32 and all(char in '0123456789abcdef' for char in signature.lower())
                timestamp = base36_to_int(timestamp_text) if is_well_formed else 0
                expired = is_well_formed and default_token_generator._num_seconds(default_token_generator._now()) - timestamp > settings.PASSWORD_RESET_TIMEOUT
            except (ValueError, TypeError, IndexError, OverflowError):
                expired = False
            detail = 'This verification link has expired. Request a new link.' if expired else 'This verification link is invalid.'
            return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)
        if user.is_active:
            return Response({'detail': 'This email address has already been verified. You can sign in.', 'status': 'already_verified'})
        user.is_active = True
        user.save(update_fields=['is_active'])
        return Response({'detail': 'Email verified. You can now sign in.', 'status': 'verified'})

class ResendVerificationView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [VerificationIPThrottle, VerificationEmailThrottle]
    @extend_schema(request=ResendVerificationSerializer, responses={200: ActionMessageSerializer, 400: ErrorResponseSerializer})
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data['email'], is_active=False).first()
        if user:
            _send_verification_email(user)
        return Response({'detail': 'If an unverified account matches that email, a verification link has been sent.'})

class ChangeVerificationEmailView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [VerificationIPThrottle, VerificationEmailThrottle]
    @extend_schema(request=ChangeVerificationEmailSerializer, responses={200: ActionMessageSerializer, 400: ErrorResponseSerializer})
    def post(self, request):
        serializer = ChangeVerificationEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        user = User.objects.filter(username__iexact=values['username'], is_active=False).first()
        if not user or not user.check_password(values['password']):
            return Response({'detail': 'The account details could not be verified.'}, status=status.HTTP_400_BAD_REQUEST)
        new_email = values['new_email'].strip().lower()
        if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
            return Response({'new_email': ['An account with this email already exists.']}, status=status.HTTP_400_BAD_REQUEST)
        user.email = new_email
        user.save(update_fields=['email'])
        _send_verification_email(user)
        return Response({'detail': 'Verification instructions have been sent to the updated email address.'})

class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]
    @extend_schema(request=PasswordResetRequestSerializer, responses={200: ActionMessageSerializer, 400: ErrorResponseSerializer})
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data['email'], is_active=True).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            url = f"{settings.FRONTEND_URL}/reset-password?{urlencode({'uid': uid, 'token': token})}"
            send_mail('Reset your Scholivyn password', f'Reset your password: {url}', settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        return Response({'detail': 'If an active account matches that email, a reset link has been sent.'})

class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: ActionMessageSerializer, 400: ErrorResponseSerializer})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user_id = force_str(urlsafe_base64_decode(serializer.validated_data['uid']))
            user = User.objects.get(pk=user_id, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            return Response({'detail': 'This reset link is invalid or expired.'}, status=status.HTTP_400_BAD_REQUEST)
        if not default_token_generator.check_token(user, serializer.validated_data['token']):
            return Response({'detail': 'This reset link is invalid or expired.'}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])
        return Response({'detail': 'Password updated. You can now sign in.'})

class MeView(generics.RetrieveAPIView):
    serializer_class=UserSerializer
    permission_classes=[permissions.IsAuthenticated]
    def get_object(self):
        return self.request.user
def health(request): return JsonResponse({'status':'ok','service':'scholivyn-api'})

def _send_verification_email(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    url = f"{settings.FRONTEND_URL}/verify-email?{urlencode({'uid': uid, 'token': token})}"
    send_mail('Verify your Scholivyn account', f'Confirm your email address: {url}', settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
    # The console backend's quoted-printable MIME output may soft-wrap this
    # long URL. Keep a raw, single-line copy aid in development only; the link
    # and token validation remain unchanged and production never logs tokens.
    if settings.DEBUG and settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
        print('\n[Scholivyn development] Copy this verification URL (one line):', flush=True)
        print(url, flush=True)
