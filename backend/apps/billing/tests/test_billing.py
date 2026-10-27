import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.models import (BillingAccount, CreditLedgerEntry, CreditReservation,
    CreditPack, CreditWallet, Invoice, PaymentOrder, PaymentTransaction, PlanPrice, Subscription,
    SubscriptionPlan, UsageEvent)
from apps.billing.services.entitlements import (FeatureUnavailable, InsufficientCredits,
    BillingError, ensure_account, finalize_usage, release_reservation, reserve_usage)
from apps.billing.services.payments import verify_checkout_signature, verify_webhook_signature
from config.local_environment import load_local_ai_environment


class BillingServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='billing-user', email='billing@example.test', password='test-pass')
        self.account = ensure_account(self.user)
        self.plan = SubscriptionPlan.objects.create(tier='free', code='free-test-configured', name='Free test', revision=2,
            available=True, feature_entitlements={'ai_review': True}, monthly_quotas={'ai_review': 1},
            credit_costs={'ai_review': 2})
        sub = Subscription.objects.get(account=self.account)
        sub.plan = self.plan
        sub.current_period_start = timezone.now() - timedelta(days=1)
        sub.save()

    @override_settings(BILLING_ENFORCEMENT_ENABLED=True)
    def test_reservation_is_idempotent_and_usage_settles_once(self):
        first = reserve_usage(self.user, feature='ai_review', idempotency_key='job:1', units=1)
        again = reserve_usage(self.user, feature='ai_review', idempotency_key='job:1', units=1)
        self.assertEqual(first.pk, again.pk)
        event = finalize_usage(first, event_key='usage:job:1', units=1, input_tokens=7, output_tokens=9)
        self.assertEqual(finalize_usage(first, event_key='usage:job:1').pk, event.pk)
        self.assertEqual(UsageEvent.objects.count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.status, CreditReservation.Status.CONSUMED)

    @override_settings(BILLING_ENFORCEMENT_ENABLED=True)
    def test_excess_usage_requires_credit_and_ledger_cannot_be_changed(self):
        first = reserve_usage(self.user, feature='ai_review', idempotency_key='job:1', units=1)
        first.status = CreditReservation.Status.RELEASED
        first.save(update_fields=['status'])
        with self.assertRaises(InsufficientCredits):
            reserve_usage(self.user, feature='ai_review', idempotency_key='job:2', units=2)
        self.assertGreaterEqual(CreditWallet.objects.get(account=self.account).prepaid_balance, 0)

    @override_settings(BILLING_ENFORCEMENT_ENABLED=True)
    def test_unstarted_reservation_releases_but_started_is_uncertain(self):
        r1 = reserve_usage(self.user, feature='ai_review', idempotency_key='job:1')
        release_reservation(r1)
        self.assertEqual(CreditReservation.objects.get(pk=r1.pk).status, CreditReservation.Status.RELEASED)
        r2 = reserve_usage(self.user, feature='ai_review', idempotency_key='job:2')
        r2.provider_started_at = timezone.now(); r2.save(update_fields=['provider_started_at'])
        release_reservation(r2)
        self.assertEqual(CreditReservation.objects.get(pk=r2.pk).status, CreditReservation.Status.UNCERTAIN)

    def test_signature_helpers_use_constant_contract(self):
        secret = 'test-secret-only'
        checkout = hmac.new(secret.encode(), b'order_1|pay_1', hashlib.sha256).hexdigest()
        self.assertTrue(verify_checkout_signature('order_1', 'pay_1', checkout, secret))
        self.assertFalse(verify_checkout_signature('order_2', 'pay_1', checkout, secret))
        body = b'{"event":"payment.captured"}'
        webhook = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(body, webhook, secret))
        self.assertFalse(verify_webhook_signature(body + b' ', webhook, secret))

    @override_settings(BILLING_ENFORCEMENT_ENABLED=True)
    def test_integer_overflow_and_ledger_queryset_mutation_are_rejected(self):
        with self.assertRaises(BillingError):
            reserve_usage(self.user, feature='ai_review', idempotency_key='overflow', units=2**63)
        entry = CreditLedgerEntry.objects.create(account=self.account, kind='admin_grant', direction='credit',
            amount=1, balance_after=1, idempotency_key='immutable-ledger-test')
        with self.assertRaises(ValidationError):
            CreditLedgerEntry.objects.filter(pk=entry.pk).update(amount=2)
        with self.assertRaises(ValidationError):
            CreditLedgerEntry.objects.filter(pk=entry.pk).delete()

    def test_plan_terms_require_new_revision(self):
        self.plan.description = 'Trying to alter published terms'
        with self.assertRaises(ValidationError):
            self.plan.save()

    def test_local_environment_loader_allows_billing_keys_but_ignores_docker_services(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            env_file = Path(directory) / '.env'
            env_file.write_text('PAYMENT_MODE=razorpay_test\nRAZORPAY_KEY_ID=rzp_test_sample\n'
                                'RAZORPAY_KEY_SECRET=local-test-only\nPOSTGRES_HOST=db\nREDIS_URL=redis://redis:6379/0\n')
            environment = {}
            load_local_ai_environment(environment, env_file, is_windows=True)
            self.assertEqual(environment['PAYMENT_MODE'], 'razorpay_test')
            self.assertEqual(environment['RAZORPAY_KEY_ID'], 'rzp_test_sample')
            self.assertNotIn('POSTGRES_HOST', environment)
            self.assertNotIn('REDIS_URL', environment)


class BillingApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='customer', email='customer@example.test', password='test-pass')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.plan = SubscriptionPlan.objects.get(tier='pro')
        self.plan.available = True; self.plan.save()
        self.price = PlanPrice.objects.create(plan=self.plan, interval='monthly', amount_minor=50000,
            currency='INR', available=True, effective_from=timezone.now())

    @override_settings(PAYMENT_MODE='mock')
    def test_mock_order_never_marks_paid_and_is_idempotent(self):
        response = self.client.post('/api/v1/billing/orders/', {'plan_price_id': self.price.pk}, format='json', secure=True, HTTP_IDEMPOTENCY_KEY='test-order-1')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'pending')
        response2 = self.client.post('/api/v1/billing/orders/', {'plan_price_id': self.price.pk}, format='json', secure=True, HTTP_IDEMPOTENCY_KEY='test-order-1')
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.data['id'], response.data['id'])
        self.assertEqual(response2.data['status'], 'pending')

    @override_settings(PAYMENT_MODE='mock')
    def test_active_paid_subscription_cannot_be_replaced_early(self):
        account = ensure_account(self.user)
        Subscription.objects.filter(account=account, status=Subscription.Status.FREE).update(status=Subscription.Status.EXPIRED)
        Subscription.objects.create(account=account, plan=self.plan, price=self.price,
            status=Subscription.Status.ACTIVE, starts_at=timezone.now(),
            current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=20))
        response = self.client.post('/api/v1/billing/orders/', {'plan_price_id': self.price.pk},
            format='json', secure=True, HTTP_IDEMPOTENCY_KEY='blocked-early-change')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PaymentOrder.objects.filter(owner=self.user).count(), 0)

    def test_customer_history_is_owner_scoped(self):
        response = self.client.get('/api/v1/billing/history/', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'orders': [], 'receipts': []})

    def test_admin_summary_denies_regular_user(self):
        response = self.client.get('/api/v1/billing/admin/summary/', secure=True)
        self.assertEqual(response.status_code, 403)

    def test_staff_customer_lookup_returns_only_billing_summary_fields(self):
        ensure_account(self.user)
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        response = self.client.get('/api/v1/billing/admin/customers/?q=customer', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['email'], 'customer@example.test')
        self.assertNotIn('password', response.data['results'][0])

    @override_settings(PAYMENT_MODE='razorpay_test', RAZORPAY_KEY_ID='rzp_test_fake',
                       RAZORPAY_KEY_SECRET='unit-test-secret')
    @patch('apps.billing.views.razorpay_fetch_payment')
    @patch('apps.billing.views.create_razorpay_order', return_value='order_test_123')
    def test_checkout_activates_only_after_signature_and_server_capture_check(self, _create_order, fetch):
        response = self.client.post('/api/v1/billing/orders/', {'plan_price_id': self.price.pk},
            format='json', secure=True, HTTP_IDEMPOTENCY_KEY='razorpay-test-order')
        self.assertEqual(response.status_code, 201)
        order_pk = response.data['id']
        payment_id = 'pay_test_123'
        secret = 'unit-test-secret'
        sig = hmac.new(secret.encode(), b'order_test_123|pay_test_123', hashlib.sha256).hexdigest()
        fetch.return_value = {'id': payment_id, 'status': 'captured', 'order_id': 'order_test_123',
            'amount': self.price.amount_minor, 'currency': self.price.currency}
        verified = self.client.post('/api/v1/billing/verify-checkout/', {
            'order_id': order_pk, 'razorpay_order_id': 'order_test_123',
            'razorpay_payment_id': payment_id, 'razorpay_signature': sig,
        }, format='json', secure=True)
        self.assertEqual(verified.status_code, 200, getattr(verified, 'data', None))
        self.assertEqual(verified.data['status'], 'paid')
        self.assertEqual(Subscription.objects.filter(account__owner=self.user, status='active').count(), 1)
        self.assertEqual(UsageEvent.objects.count(), 0)

    @override_settings(PAYMENT_MODE='razorpay_test', RAZORPAY_KEY_ID='rzp_test_fake', RAZORPAY_KEY_SECRET='unit-test-secret')
    def test_forged_checkout_signature_does_not_activate_plan(self):
        account = ensure_account(self.user)
        order = __import__('apps.billing.models', fromlist=['PaymentOrder']).PaymentOrder.objects.create(
            owner=self.user, account=account, plan_price=self.price,
            purpose='subscription', provider='razorpay_test', provider_order_id='order_test_123',
            amount_minor=self.price.amount_minor, currency=self.price.currency, idempotency_key='forged-order')
        response = self.client.post('/api/v1/billing/verify-checkout/', {
            'order_id': str(order.pk), 'razorpay_order_id': 'order_test_123',
            'razorpay_payment_id': 'pay_test_fake', 'razorpay_signature': 'forged',
        }, format='json', secure=True)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Subscription.objects.filter(account=account, status='active').count(), 0)

    @override_settings(PAYMENT_MODE='razorpay_test', RAZORPAY_KEY_ID='rzp_test_fake', RAZORPAY_KEY_SECRET='unit-test-secret')
    @patch('apps.billing.views.razorpay_fetch_payment')
    def test_checkout_rejects_provider_response_with_different_payment_id(self, fetch):
        account = ensure_account(self.user)
        order = PaymentOrder.objects.create(owner=self.user, account=account, plan_price=self.price,
            purpose='subscription', provider='razorpay_test', provider_order_id='order_test_identity',
            amount_minor=self.price.amount_minor, currency=self.price.currency,
            idempotency_key='payment-id-identity-check')
        callback_payment_id = 'pay_callback_id'
        signature = hmac.new(b'unit-test-secret',
            f'order_test_identity|{callback_payment_id}'.encode(), hashlib.sha256).hexdigest()
        fetch.return_value = {'id': 'pay_different_id', 'status': 'captured',
            'order_id': 'order_test_identity', 'amount': self.price.amount_minor,
            'currency': self.price.currency}
        response = self.client.post('/api/v1/billing/verify-checkout/', {
            'order_id': str(order.pk), 'razorpay_order_id': 'order_test_identity',
            'razorpay_payment_id': callback_payment_id, 'razorpay_signature': signature,
        }, format='json', secure=True)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PaymentTransaction.objects.filter(order=order).exists())
        self.assertFalse(Subscription.objects.filter(account=account, status=Subscription.Status.ACTIVE).exists())

    @override_settings(PAYMENT_MODE='razorpay_test', RAZORPAY_WEBHOOK_SECRET='webhook-unit-secret')
    def test_webhook_is_signed_idempotent_and_captured_only(self):
        account = ensure_account(self.user)
        order = PaymentOrder.objects.create(owner=self.user, account=account, plan_price=self.price,
            purpose='subscription', provider='razorpay_test', provider_order_id='order_hook_1',
            amount_minor=self.price.amount_minor, currency=self.price.currency, idempotency_key='hook-order')
        failed_payload = {'id':'evt_failed','event':'payment.failed','payload':{'payment':{'entity':{
            'id':'pay_hook_1','status':'failed','order_id':'order_hook_1','amount':self.price.amount_minor,'currency':'INR'}}}}
        def post_event(payload):
            raw = json.dumps(payload, separators=(',', ':')).encode()
            signature = hmac.new(b'webhook-unit-secret', raw, hashlib.sha256).hexdigest()
            return self.client.post('/api/v1/billing/webhooks/razorpay/', data=raw,
                content_type='application/json', secure=True, HTTP_X_RAZORPAY_SIGNATURE=signature)
        self.assertEqual(post_event(failed_payload).data['status'], 'ignored')
        captured_payload = {'id':'evt_capture','event':'payment.captured','payload':{'payment':{'entity':{
            'id':'pay_hook_1','status':'captured','order_id':'order_hook_1','amount':self.price.amount_minor,'currency':'INR'}}}}
        self.assertEqual(post_event(captured_payload).data['status'], 'processed')
        self.assertEqual(post_event(captured_payload).data['status'], 'duplicate')
        self.assertEqual(PaymentTransaction.objects.filter(order=order).count(), 1)
        self.assertEqual(Invoice.objects.filter(owner=self.user, transaction__order=order).count(), 1)
        self.assertTrue(Subscription.objects.filter(account=account, plan=self.plan, status='active').exists())

    def test_receipt_download_is_owner_scoped_and_pdf_only_after_verified_capture(self):
        account = ensure_account(self.user)
        order = PaymentOrder.objects.create(owner=self.user, account=account, plan_price=self.price,
            purpose='subscription', provider='mock', amount_minor=self.price.amount_minor,
            currency='INR', idempotency_key='receipt-order', status='paid', paid_at=timezone.now())
        transaction = PaymentTransaction.objects.create(order=order, provider_payment_id='verified-test-payment',
            status=PaymentTransaction.Status.CAPTURED, amount_minor=order.amount_minor, currency='INR', verified_at=timezone.now())
        invoice = Invoice.objects.create(owner=self.user, account=account, transaction=transaction,
            invoice_number='TEST-RECEIPT-1', amount_minor=order.amount_minor, currency='INR',
            description='Test receipt', issued_at=timezone.now())
        response = self.client.get(f'/api/v1/billing/invoices/{invoice.pk}/download/', secure=True)
        self.assertEqual(response.status_code, 200, getattr(response, 'data', None))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        other = get_user_model().objects.create_user(username='other-customer', email='other@example.test', password='pass')
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(f'/api/v1/billing/invoices/{invoice.pk}/download/', secure=True).status_code, 404)

    @override_settings(PAYMENT_MODE='razorpay_test', RAZORPAY_KEY_ID='rzp_test_fake', RAZORPAY_KEY_SECRET='unit-test-secret')
    @patch('apps.billing.views.razorpay_fetch_payment')
    @patch('apps.billing.views.create_razorpay_order', return_value='order_credit_1')
    def test_credit_topup_is_granted_only_after_verified_capture(self, _create, fetch):
        pack = CreditPack.objects.create(code='test-pack', name='Test pack', amount_minor=10000,
            currency='INR', credits=25, available=True, effective_from=timezone.now())
        created = self.client.post('/api/v1/billing/orders/', {'purpose':'credit_topup','credit_pack_id':pack.pk},
            format='json', secure=True, HTTP_IDEMPOTENCY_KEY='test-credit-order')
        self.assertEqual(created.status_code, 201)
        signature = hmac.new(b'unit-test-secret', b'order_credit_1|pay_credit_1', hashlib.sha256).hexdigest()
        fetch.return_value = {'id':'pay_credit_1','status':'captured','order_id':'order_credit_1',
            'amount':pack.amount_minor,'currency':pack.currency}
        verified = self.client.post('/api/v1/billing/verify-checkout/', {
            'order_id': created.data['id'], 'razorpay_order_id':'order_credit_1',
            'razorpay_payment_id':'pay_credit_1', 'razorpay_signature':signature,
        }, format='json', secure=True)
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(CreditWallet.objects.get(account__owner=self.user).prepaid_balance, 25)
        self.assertEqual(CreditLedgerEntry.objects.filter(account__owner=self.user, kind='purchase').count(), 1)

