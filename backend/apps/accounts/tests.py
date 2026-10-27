from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework import status
from urllib.parse import parse_qs, urlsplit
from contextlib import redirect_stdout
from io import StringIO
import re
from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.test import RequestFactory, TestCase
from django.urls import reverse
User = get_user_model()


class AccountAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='admin-password-123'
        )
        self.user = User.objects.create_user(
            username='ada', email='ada@example.com', password='strong-pass-123',
            full_name='Ada Lovelace', is_active=False,
        )
        self.model_admin = admin.site._registry[User]
        self.request_factory = RequestFactory()

    def test_user_admin_lists_profile_and_permission_controls(self):
        self.assertEqual(
            self.model_admin.list_display,
            ('username', 'email', 'full_name', 'role', 'is_active', 'is_staff', 'is_superuser', 'date_joined'),
        )
        self.assertEqual(self.model_admin.search_fields, ('username', 'email', 'full_name'))
        self.assertEqual(self.model_admin.list_filter, ('is_active', 'role', 'is_staff', 'is_superuser'))

        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:accounts_user_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ada Lovelace')
        self.assertContains(response, 'Date joined')

    def test_password_uses_django_change_password_page_without_exposing_secret(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('admin:accounts_user_change', args=(self.user.pk,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reset password')
        password_page = self.client.get(
            reverse('admin:auth_user_password_change', args=(self.user.pk,))
        )
        self.assertEqual(password_page.status_code, 200)
        changed = self.client.post(
            reverse('admin:auth_user_password_change', args=(self.user.pk,)),
            {'password1': 'replacement-password-456', 'password2': 'replacement-password-456'},
        )
        self.assertEqual(changed.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('replacement-password-456'))
        self.assertNotEqual(self.user.password, 'replacement-password-456')
        self.assertNotContains(response, 'strong-pass-123')
        self.assertNotContains(response, self.user.password)

    def test_only_superusers_can_edit_role_or_django_permissions(self):
        staff = User.objects.create_user(
            username='manager', password='manager-password-123', is_staff=True
        )
        staff.user_permissions.add(Permission.objects.get(codename='change_user'))
        request = self.request_factory.get('/')
        request.user = staff
        readonly = set(self.model_admin.get_readonly_fields(request, self.user))
        self.assertTrue({'role', 'is_staff', 'is_superuser', 'groups', 'user_permissions'} <= readonly)
        self.assertIn('is_active', readonly)

        request.user = self.superuser
        superuser_readonly = set(self.model_admin.get_readonly_fields(request, self.user))
        self.assertFalse({'role', 'is_staff', 'is_superuser', 'groups', 'user_permissions'} & superuser_readonly)
        self.assertIn('is_active', superuser_readonly)

    def test_admin_created_accounts_start_inactive(self):
        new_user = User(
            username='new-admin-user', email='new@example.com', is_active=True
        )
        new_user.set_password('new-admin-password-123')
        request = self.request_factory.post('/')
        request.user = self.superuser
        self.model_admin.save_model(request, new_user, form=None, change=False)
        new_user.refresh_from_db()
        self.assertFalse(new_user.is_active)

    def test_user_groups_and_permissions_can_be_assigned_and_persist(self):
        group = Group.objects.create(name='Researchers')
        permission = Permission.objects.get(codename='change_user')

        self.user.groups.add(group)
        self.user.user_permissions.add(permission)
        self.user.refresh_from_db()

        self.assertTrue(self.user.groups.filter(pk=group.pk).exists())
        self.assertTrue(self.user.user_permissions.filter(pk=permission.pk).exists())

@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    FRONTEND_URL='http://localhost:3001',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'auth-api-tests'}},
)
class AccountApiTests(APITestCase):
    def setUp(self):
        cache.clear()

    def test_register_requires_email_verification_before_login(self):
        response=self.client.post('/api/v1/auth/register/', {'username':'ada','email':'ada@example.com','password':'strong-pass-123','full_name':'Ada Lovelace'}, format='json')
        self.assertEqual(response.status_code,status.HTTP_201_CREATED)
        user=User.objects.get(username='ada')
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox),1)
        self.assertIn('http://localhost:3001/verify-email?',mail.outbox[0].body)
        self.assertIn('uid=',mail.outbox[0].body)
        login=self.client.post('/api/v1/auth/login/', {'username':'ada','password':'strong-pass-123'}, format='json')
        self.assertEqual(login.status_code,status.HTTP_401_UNAUTHORIZED)

    def test_email_verification_then_login_and_me(self):
        self.client.post('/api/v1/auth/register/', {'username':'ada','email':'ada@example.com','password':'strong-pass-123','full_name':'Ada Lovelace'}, format='json')
        user=User.objects.get(username='ada')
        match=re.search(r'http://localhost:3001/verify-email\?([^\s]+)',mail.outbox[0].body)
        self.assertIsNotNone(match)
        payload={key: values[0] for key, values in parse_qs(urlsplit(match.group(0)).query).items()}
        self.assertEqual(set(payload), {'uid', 'token'})
        verified=self.client.post('/api/v1/auth/verify-email/',payload,format='json')
        self.assertEqual(verified.status_code,status.HTTP_200_OK)
        self.assertEqual(verified.data['status'], 'verified')
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        repeated=self.client.post('/api/v1/auth/verify-email/',payload,format='json')
        self.assertEqual(repeated.status_code,status.HTTP_200_OK)
        self.assertEqual(repeated.data['status'], 'already_verified')
        login=self.client.post('/api/v1/auth/login/', {'username':'ada@example.com','password':'strong-pass-123'}, format='json')
        self.assertEqual(login.status_code,status.HTTP_200_OK)
        token=login.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        profile=self.client.get('/api/v1/auth/me/')
        self.assertEqual(profile.status_code,status.HTTP_200_OK)
        self.assertEqual(profile.data['email'],'ada@example.com')
        refreshed=self.client.post('/api/v1/auth/refresh/',{'refresh':login.data['refresh']},format='json')
        self.assertEqual(refreshed.status_code,status.HTTP_200_OK)
        self.assertIn('access',refreshed.data)

    def test_console_copy_url_completes_registration_to_activation(self):
        console = StringIO()
        with override_settings(DEBUG=True, EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'):
            with redirect_stdout(console):
                registered = self.client.post('/api/v1/auth/register/', {
                    'username': 'console-ada', 'email': 'console-ada@example.com',
                    'password': 'strong-pass-123', 'full_name': 'Console Ada',
                }, format='json')
        self.assertEqual(registered.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='console-ada')
        self.assertFalse(user.is_active)

        output = console.getvalue().splitlines()
        marker = '[Scholivyn development] Copy this verification URL (one line):'
        self.assertIn(marker, output)
        url = output[output.index(marker) + 1]
        self.assertIn('http://localhost:3001/verify-email?', url)
        self.assertIn(url, output)  # a single unwrapped, directly copyable line
        payload = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        self.assertEqual(set(payload), {'uid', 'token'})

        verified = self.client.post('/api/v1/auth/verify-email/', payload, format='json')
        self.assertEqual(verified.status_code, status.HTTP_200_OK)
        self.assertEqual(verified.data['status'], 'verified')
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_resend_verification_is_generic_and_sends_to_unverified_account(self):
        User.objects.create_user(username='ada',email='ada@example.com',password='strong-pass-123',is_active=False)
        response=self.client.post('/api/v1/auth/verify-email/resend/',{'email':'ada@example.com'},format='json')
        self.assertEqual(response.status_code,status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox),1)
        unknown=self.client.post('/api/v1/auth/verify-email/resend/',{'email':'missing@example.com'},format='json')
        self.assertEqual(unknown.status_code,status.HTTP_200_OK)
        self.assertEqual(unknown.data['detail'],response.data['detail'])

    def test_change_verification_email_requires_account_password(self):
        user=User.objects.create_user(username='ada',email='ada@example.com',password='strong-pass-123',is_active=False)
        denied=self.client.post('/api/v1/auth/verify-email/change-email/',{'username':'ada','password':'wrong-password','new_email':'new@example.com'},format='json')
        self.assertEqual(denied.status_code,status.HTTP_400_BAD_REQUEST)
        response=self.client.post('/api/v1/auth/verify-email/change-email/',{'username':'ada','password':'strong-pass-123','new_email':' NEW@example.com '},format='json')
        self.assertEqual(response.status_code,status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(user.email,'new@example.com')
        self.assertEqual(mail.outbox[-1].to,['new@example.com'])

    def test_resend_verification_is_rate_limited_per_email(self):
        for _ in range(3):
            result=self.client.post('/api/v1/auth/verify-email/resend/',{'email':'rate@example.com'},format='json')
            self.assertEqual(result.status_code,status.HTTP_200_OK)
        limited=self.client.post('/api/v1/auth/verify-email/resend/',{'email':'rate@example.com'},format='json')
        self.assertEqual(limited.status_code,status.HTTP_429_TOO_MANY_REQUESTS)

    def test_expired_and_invalid_verification_tokens_are_rejected(self):
        user=User.objects.create_user(username='ada',email='ada@example.com',password='strong-pass-123',is_active=False)
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        uid=urlsafe_base64_encode(force_bytes(user.pk))
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            expired=self.client.post('/api/v1/auth/verify-email/',{'uid':uid,'token':default_token_generator.make_token(user)},format='json')
        self.assertEqual(expired.status_code,status.HTTP_400_BAD_REQUEST)
        self.assertIn('expired', expired.data['detail'])
        invalid=self.client.post('/api/v1/auth/verify-email/',{'uid':uid,'token':'bad-token'},format='json')
        self.assertEqual(invalid.status_code,status.HTTP_400_BAD_REQUEST)
        self.assertIn('invalid', invalid.data['detail'])

    def test_password_reset_is_generic_for_unknown_email(self):
        response=self.client.post('/api/v1/auth/password-reset/',{'email':'unknown@example.com'},format='json')
        self.assertEqual(response.status_code,status.HTTP_200_OK)
        self.assertEqual(response.data['detail'],'If an active account matches that email, a reset link has been sent.')

    def test_password_reset_link_changes_password(self):
        user=User.objects.create_user(username='ada',email='ada@example.com',password='old-password-123')
        self.client.post('/api/v1/auth/password-reset/',{'email':user.email},format='json')
        self.assertEqual(len(mail.outbox),1)
        import re
        match=re.search(r'/reset-password\?uid=([^&]+)&token=([^\s]+)',mail.outbox[0].body)
        self.assertIsNotNone(match)
        response=self.client.post('/api/v1/auth/password-reset/confirm/',{'uid':match.group(1),'token':match.group(2),'new_password':'new-password-456'},format='json')
        self.assertEqual(response.status_code,status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.check_password('new-password-456'))

    def test_me_requires_authentication(self):
        response=self.client.get('/api/v1/auth/me/')
        self.assertEqual(response.status_code,status.HTTP_401_UNAUTHORIZED)
