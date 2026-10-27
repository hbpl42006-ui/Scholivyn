from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
User=get_user_model()
class RegisterSerializer(serializers.ModelSerializer):
    password=serializers.CharField(write_only=True, min_length=8)
    class Meta: model=User; fields=('email','username','password','full_name','role')
    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return email
    def validate_username(self, value):
        username = value.strip()
        if User.objects.filter(username__iexact=username).exists():
            raise serializers.ValidationError('This username is already taken.')
        return username
    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
class UserSerializer(serializers.ModelSerializer):
    is_staff = serializers.BooleanField(read_only=True)
    class Meta: model=User; fields=('id','username','email','full_name','role','date_joined','is_staff')

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8, write_only=True)
    def validate_new_password(self, value):
        from django.contrib.auth.password_validation import validate_password
        validate_password(value)
        return value

class EmailVerificationSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()

class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()

class ChangeVerificationEmailSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    new_email = serializers.EmailField()

class ActionMessageSerializer(serializers.Serializer):
    detail = serializers.CharField()
    status = serializers.CharField(required=False)

class ErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False)

class EmailOrUsernameTokenSerializer(TokenObtainPairSerializer):
    """Accept either the username or the email shown by the login form."""
    def validate(self, attrs):
        identifier = attrs.get(self.username_field, '')
        if '@' in identifier:
            username = User.objects.filter(email__iexact=identifier.strip()).values_list('username', flat=True).first()
            if username:
                attrs[self.username_field] = username
        return super().validate(attrs)
