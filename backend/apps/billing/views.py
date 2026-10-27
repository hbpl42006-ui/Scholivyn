import hashlib
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.billing.models import (BillingAccount, BillingAuditLog, CreditWallet, Invoice,
    CreditPack, CreditReservation, PaymentOrder, PaymentTransaction, PlanPrice, Subscription, UsageEvent, WebhookEvent)
from apps.intelligence.models import AIUsageRecord
from apps.billing.services.entitlements import current_subscription, ensure_account
from apps.billing.services.lifecycle import record_captured_payment
from apps.billing.services.payments import (PaymentError, razorpay_fetch_payment,
    verify_checkout_signature, verify_webhook_signature, verified_amount_matches)


def serialize_plan(plan):
    now = timezone.now()
    return {'id': plan.pk, 'code': plan.code, 'tier': plan.tier, 'name': plan.name,
        'description': plan.description, 'features': plan.feature_entitlements,
        'monthly_quotas': plan.monthly_quotas,
        'prices': [{'id': p.pk, 'interval': p.interval, 'amount_minor': p.amount_minor,
                    'currency': p.currency} for p in plan.prices.filter(available=True, effective_from__lte=now)
                    .filter(Q(effective_until__isnull=True) | Q(effective_until__gt=now))]}


class BillingOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        account = ensure_account(request.user)
        wallet, _ = CreditWallet.objects.get_or_create(account=account)
        sub = current_subscription(account)
        from django.db.models import Count, Sum
        usage = list(UsageEvent.objects.filter(account=account,
            measured_at__year=timezone.now().year, measured_at__month=timezone.now().month)
            .values('feature').annotate(units=Sum('units'), input_tokens=Sum('input_tokens'),
                output_tokens=Sum('output_tokens'), credits=Sum('credits_debited')))
        settled_job_ids = CreditReservation.objects.filter(account=account, reference_type='analysis_job').values_list('reference_id', flat=True)
        historical_ai = AIUsageRecord.objects.filter(user=request.user,
            created_at__year=timezone.now().year, created_at__month=timezone.now().month).exclude(
                job_id__in=settled_job_ids).aggregate(units=Count('job_id', distinct=True),
                    input=Sum('input_tokens'), output=Sum('output_tokens'))
        if historical_ai['units']:
            usage.append({'feature': 'ai_review', 'units': historical_ai['units'],
                'input_tokens': historical_ai['input'] or 0, 'output_tokens': historical_ai['output'] or 0,
                'credits': 0})
        usage_by_feature = {row['feature']: int(row['units'] or 0) for row in usage}
        quotas = sub.plan.monthly_quotas if sub else {}
        remaining = {feature: max(0, int(limit) - usage_by_feature.get(feature, 0))
                     for feature, limit in quotas.items()}
        return Response({'account': {'billing_email': account.billing_email, 'display_name': account.display_name},
            'subscription': ({'status': sub.status, 'plan': serialize_plan(sub.plan),
                'period_start': sub.current_period_start, 'period_end': sub.current_period_end,
                'cancel_at_period_end': sub.cancel_at_period_end} if sub else None),
            'credits': wallet.prepaid_balance, 'currency': 'INR', 'monthly_usage': usage,
            'quota_remaining': remaining,
            'payment_mode': settings.PAYMENT_MODE})

    def patch(self, request):
        account = ensure_account(request.user)
        email = serializers.EmailField(required=False, allow_blank=True).run_validation(request.data.get('billing_email')) if 'billing_email' in request.data else account.billing_email
        name_field = serializers.CharField(required=False, allow_blank=True, max_length=160)
        name = name_field.run_validation(request.data.get('display_name')) if 'display_name' in request.data else account.display_name
        changed = []
        if email != account.billing_email: account.billing_email = email; changed.append('billing_email')
        if name != account.display_name: account.display_name = name; changed.append('display_name')
        if changed:
            account.save(update_fields=changed + ['updated_at'])
            BillingAuditLog.objects.create(actor=request.user, account=account, action='billing_contact_updated',
                object_type='BillingAccount', object_id=str(account.pk), details={'updated_fields': changed})
        return Response({'billing_email': account.billing_email, 'display_name': account.display_name})


class PlanListView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        from apps.billing.models import SubscriptionPlan
        plans = SubscriptionPlan.objects.filter(available=True).prefetch_related('prices')
        return Response([serialize_plan(p) for p in plans])


class CreditPackListView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        now = timezone.now()
        packs = CreditPack.objects.filter(available=True, effective_from__lte=now).filter(
            Q(effective_until__isnull=True) | Q(effective_until__gt=now))
        return Response([{'id': pack.pk, 'code': pack.code, 'name': pack.name,
            'amount_minor': pack.amount_minor, 'currency': pack.currency, 'credits': pack.credits}
            for pack in packs])


class BillingHistoryView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        account = ensure_account(request.user)
        orders = PaymentOrder.objects.filter(owner=request.user).order_by('-created_at')[:100]
        receipts = Invoice.objects.filter(owner=request.user).order_by('-issued_at')[:100]
        return Response({'orders': [{'id': str(o.pk), 'purpose': o.purpose, 'amount_minor': o.amount_minor,
            'currency': o.currency, 'status': o.status, 'created_at': o.created_at,
            'paid_at': o.paid_at} for o in orders],
            'receipts': [{'id': str(i.pk), 'invoice_number': i.invoice_number, 'status': i.status,
            'amount_minor': i.amount_minor, 'tax_minor': i.tax_minor, 'currency': i.currency,
            'description': i.description, 'issued_at': i.issued_at} for i in receipts]})


class CreateOrderView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'billing_order'

    def post(self, request):
        purpose = request.data.get('purpose', PaymentOrder.Purpose.SUBSCRIPTION)
        price, pack = None, None
        now = timezone.now()
        if purpose == PaymentOrder.Purpose.SUBSCRIPTION:
            try:
                price_id = serializers.IntegerField(min_value=1).run_validation(request.data.get('plan_price_id'))
            except serializers.ValidationError:
                return Response({'plan_price_id': ['A valid configured plan price is required.']}, status=400)
            price = PlanPrice.objects.filter(pk=price_id, available=True, plan__available=True,
                effective_from__lte=now).filter(Q(effective_until__isnull=True) | Q(effective_until__gt=now)).select_related('plan').first()
            if not price or price.amount_minor <= 0:
                return Response({'detail': 'This plan price is unavailable.'}, status=400)
            amount_minor, currency, credits_to_grant = price.amount_minor, price.currency, 0
        elif purpose == PaymentOrder.Purpose.CREDIT_TOPUP:
            try:
                pack_id = serializers.IntegerField(min_value=1).run_validation(request.data.get('credit_pack_id'))
            except serializers.ValidationError:
                return Response({'credit_pack_id': ['A valid configured credit pack is required.']}, status=400)
            pack = CreditPack.objects.filter(pk=pack_id, available=True, effective_from__lte=now).filter(
                Q(effective_until__isnull=True) | Q(effective_until__gt=now)).first()
            if not pack:
                return Response({'detail': 'This credit pack is unavailable.'}, status=400)
            amount_minor, currency, credits_to_grant = pack.amount_minor, pack.currency, pack.credits
        else:
            return Response({'purpose': ['Choose subscription or credit_topup.']}, status=400)
        key = (request.headers.get('Idempotency-Key') or request.data.get('idempotency_key') or '').strip()
        if not key or len(key) > 180:
            return Response({'detail': 'A valid Idempotency-Key is required.'}, status=400)
        now = timezone.now()
        account = ensure_account(request.user)
        if purpose == PaymentOrder.Purpose.SUBSCRIPTION:
            active_subscription = current_subscription(account)
            if active_subscription and active_subscription.status != Subscription.Status.FREE:
                return Response({'detail': 'A paid subscription is already active. Plan changes are available after its current period ends.'}, status=409)
            if settings.PAYMENT_MODE == 'razorpay_test':
                PaymentOrder.objects.filter(owner=request.user, purpose=purpose, provider='razorpay_test',
                    status=PaymentOrder.Status.PENDING, created_at__lte=now - timedelta(minutes=30)).update(
                        status=PaymentOrder.Status.CANCELLED, updated_at=now)
                if PaymentOrder.objects.filter(owner=request.user, purpose=purpose, provider='razorpay_test',
                    status=PaymentOrder.Status.PENDING).exists():
                    return Response({'detail': 'A Razorpay test checkout is already pending. Complete it or wait 30 minutes before creating another.'}, status=409)
        existing = PaymentOrder.objects.filter(owner=request.user, idempotency_key=key).first()
        if existing:
            if (existing.plan_price_id != (price.pk if price else None)
                    or existing.credit_pack_id != (pack.pk if pack else None) or existing.purpose != purpose):
                return Response({'detail': 'This idempotency key was already used for a different order.'}, status=409)
            return Response({'id': str(existing.pk), 'status': existing.status,
                'provider': existing.provider, 'amount_minor': existing.amount_minor,
                'currency': existing.currency, 'provider_order_id': existing.provider_order_id})
        provider = settings.PAYMENT_MODE
        if provider not in ('mock', 'razorpay_test'):
            return Response({'detail': 'Payment provider is disabled.'}, status=503)
        try:
            with transaction.atomic():
                order = PaymentOrder.objects.create(owner=request.user, account=account,
                    plan_price=price, credit_pack=pack, purpose=purpose, provider=provider,
                    amount_minor=amount_minor, currency=currency, credits_to_grant=credits_to_grant, idempotency_key=key,
                    status=PaymentOrder.Status.PENDING)
        except IntegrityError:
            order = PaymentOrder.objects.filter(owner=request.user, idempotency_key=key).first()
            if not order or order.plan_price_id != (price.pk if price else None) or order.credit_pack_id != (pack.pk if pack else None):
                return Response({'detail': 'This idempotency key was already used for a different order.'}, status=409)
            return Response({'id': str(order.pk), 'status': order.status, 'provider': order.provider,
                'amount_minor': order.amount_minor, 'currency': order.currency,
                'provider_order_id': order.provider_order_id})
        if provider == 'razorpay_test':
            try:
                provider_order_id = create_razorpay_order(order)
            except PaymentError:
                order.status = PaymentOrder.Status.FAILED
                order.save(update_fields=['status', 'updated_at'])
                return Response({'detail': 'Test checkout could not be created. Try again later.'}, status=502)
            order.provider_order_id = provider_order_id
            order.save(update_fields=['provider_order_id', 'updated_at'])
        BillingAuditLog.objects.create(actor=request.user, account=account,
            action='payment_order_created', object_type='PaymentOrder', object_id=str(order.pk),
            details={'provider': provider, 'amount_minor': order.amount_minor, 'currency': order.currency})
        return Response({'id': str(order.pk), 'status': order.status, 'provider': provider,
            'amount_minor': order.amount_minor, 'currency': order.currency,
            'provider_order_id': order.provider_order_id,
            **({'key_id': settings.RAZORPAY_KEY_ID} if provider == 'razorpay_test' else {})}, status=201)


def create_razorpay_order(order):
    import base64
    import urllib.error
    import urllib.request
    if settings.PAYMENT_MODE != 'razorpay_test' or not settings.RAZORPAY_KEY_ID.startswith('rzp_test_') or not settings.RAZORPAY_KEY_SECRET:
        raise PaymentError('Razorpay test credentials are not configured.')
    payload = json.dumps({'amount': order.amount_minor, 'currency': order.currency,
        'receipt': str(order.pk), 'notes': {'scholivyn_order': str(order.pk)}}).encode()
    auth = base64.b64encode(f'{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}'.encode()).decode()
    req = urllib.request.Request('https://api.razorpay.com/v1/orders', data=payload,
        headers={'Authorization': 'Basic ' + auth, 'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            result = json.loads(response.read(32768))
    except Exception as exc:
        raise PaymentError('Test checkout service is unavailable.') from exc
    if not isinstance(result, dict) or not isinstance(result.get('id'), str):
        raise PaymentError('Test checkout returned an invalid response.')
    return result['id']


class VerifyCheckoutView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'billing_verify'
    def post(self, request):
        try:
            order_id = serializers.IntegerField(min_value=1).run_validation(request.data.get('order_id'))
        except serializers.ValidationError:
            return Response({'detail': 'Payment order was not found.'}, status=404)
        order = PaymentOrder.objects.filter(pk=order_id, owner=request.user,
            provider='razorpay_test').first()
        if not order:
            return Response({'detail': 'Payment order was not found.'}, status=404)
        if request.data.get('razorpay_order_id') != order.provider_order_id:
            return Response({'detail': 'Payment order does not match this checkout.'}, status=400)
        payment_id = request.data.get('razorpay_payment_id', '')
        signature = request.data.get('razorpay_signature', '')
        if not verify_checkout_signature(order.provider_order_id, payment_id, signature, settings.RAZORPAY_KEY_SECRET):
            return Response({'detail': 'Payment signature could not be verified.'}, status=400)
        try:
            payment = razorpay_fetch_payment(payment_id)
        except PaymentError:
            return Response({'detail': 'Payment verification is temporarily unavailable.'}, status=503)
        if not verified_amount_matches(payment, order, expected_payment_id=payment_id):
            return Response({'detail': 'Payment is not captured or does not match this order.'}, status=400)
        try:
            txn = record_captured_payment(order, payment_id=payment_id,
                amount_minor=payment['amount'], currency=payment['currency'], provider_reference=payment_id)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=409)
        return Response({'status': 'paid', 'transaction_id': str(txn.pk)})


class RazorpayWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'billing_webhook'
    def post(self, request):
        if settings.PAYMENT_MODE != 'razorpay_test' or not settings.RAZORPAY_WEBHOOK_SECRET:
            return Response({'detail': 'Webhook integration is disabled.'}, status=503)
        raw = request.body
        if len(raw) > 1024 * 1024:
            return Response({'detail': 'Webhook payload is too large.'}, status=413)
        signature = request.headers.get('X-Razorpay-Signature', '')
        if not verify_webhook_signature(raw, signature, settings.RAZORPAY_WEBHOOK_SECRET):
            return Response({'detail': 'Invalid webhook signature.'}, status=400)
        try:
            payload = json.loads(raw)
            event_id = request.headers.get('X-Razorpay-Event-Id') or payload.get('id')
            event_type = payload.get('event', '')
            payment = payload['payload']['payment']['entity']
            if not isinstance(event_id, str) or not event_id or len(event_id) > 180:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return Response({'detail': 'Malformed webhook payload.'}, status=400)
        digest = hashlib.sha256(raw).hexdigest()
        event, created = WebhookEvent.objects.get_or_create(provider='razorpay', event_id=event_id,
            defaults={'event_type': event_type[:80], 'payload_sha256': digest, 'signature_valid': True})
        if not created and event.payload_sha256 != digest:
            return Response({'detail': 'Webhook event identifier conflicts with previously received content.'}, status=409)
        if not created and event.status == WebhookEvent.Status.PROCESSED:
            return Response({'status': 'duplicate'})
        if event_type != 'payment.captured' or payment.get('status') != 'captured':
            event.status = WebhookEvent.Status.IGNORED
            event.processed_at = timezone.now()
            event.save(update_fields=['status', 'processed_at'])
            return Response({'status': 'ignored'})
        order = PaymentOrder.objects.filter(provider='razorpay_test', provider_order_id=payment.get('order_id')).first()
        if not order or not verified_amount_matches(payment, order):
            event.status = WebhookEvent.Status.FAILED
            event.error_category = 'order_mismatch'
            event.save(update_fields=['status', 'error_category'])
            return Response({'detail': 'Payment does not match a valid order.'}, status=400)
        try:
            record_captured_payment(order, payment_id=payment['id'], amount_minor=payment['amount'],
                currency=payment['currency'], provider_reference=payment['id'])
        except ValueError:
            event.status = WebhookEvent.Status.FAILED
            event.error_category = 'duplicate_payment'
            event.save(update_fields=['status', 'error_category'])
            return Response({'detail': 'Payment has already been reconciled.'}, status=409)
        event.status = WebhookEvent.Status.PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])
        return Response({'status': 'processed'})


class AdminBillingSummaryView(APIView):
    permission_classes = [IsAdminUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'billing_admin'
    def get(self, request):
        from django.db.models import Count, Sum
        from apps.billing.models import SubscriptionPlan
        verified = PaymentTransaction.objects.filter(status=PaymentTransaction.Status.CAPTURED,
            verified_at__isnull=False)
        revenue = verified.aggregate(total=Sum('amount_minor'))['total'] or 0
        provider_cost = AIUsageRecord.objects.aggregate(total=Sum('estimated_cost'))['total']
        plans = list(Subscription.objects.filter(status__in=['active', 'trialing', 'free'])
            .values('plan__tier').annotate(customers=Count('account_id')))
        warnings = []
        if settings.PAYMENT_MODE == 'mock': warnings.append('Payments are in mock mode; no plan can be activated from a mock order.')
        if not SubscriptionPlan.objects.filter(available=True).exists(): warnings.append('No subscription plans are published.')
        if not settings.BILLING_ENFORCEMENT_ENABLED: warnings.append('Usage enforcement is disabled.')
        if not settings.SUBSCRIPTION_RENEWALS_ENABLED: warnings.append('Automatic renewals are disabled.')
        if settings.PAYMENT_MODE == 'razorpay_test' and not settings.RAZORPAY_WEBHOOK_SECRET:
            warnings.append('Razorpay webhook verification is not configured.')
        return Response({'verified_revenue_minor': revenue, 'currency': 'INR',
            'verified_captures': verified.count(), 'plan_distribution': plans,
            'pending_orders': PaymentOrder.objects.filter(status='pending').count(),
            'failed_orders': PaymentOrder.objects.filter(status='failed').count(),
            'available_plans': SubscriptionPlan.objects.filter(available=True).count(),
            'recorded_ai_provider_cost': str(provider_cost) if provider_cost is not None else None,
            'ai_usage_records': AIUsageRecord.objects.count(),
            'warnings': warnings, 'warning': 'Revenue counts only verified captured transactions.'})


class AdminCustomerLookupView(APIView):
    permission_classes = [IsAdminUser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'billing_admin'
    def get(self, request):
        query = (request.query_params.get('q') or '').strip()
        if len(query) < 2 or len(query) > 120:
            return Response({'detail': 'Enter at least 2 characters and no more than 120.'}, status=400)
        search = Q(owner__email__icontains=query) | Q(owner__username__icontains=query)
        try: search |= Q(customer_reference=uuid.UUID(query))
        except (ValueError, TypeError): pass
        accounts = BillingAccount.objects.filter(search).select_related('owner').prefetch_related(
                'subscriptions__plan', 'subscriptions__price', 'credit_wallet')[:50]
        rows = []
        for account in accounts:
            sub = account.subscriptions.order_by('-starts_at').first()
            rows.append({'customer_reference': str(account.customer_reference),
                'user_id': str(account.owner_id), 'username': account.owner.username,
                'email': account.owner.email, 'billing_email': account.billing_email,
                'subscription': ({'plan': sub.plan.name, 'status': sub.status,
                    'period_end': sub.current_period_end} if sub else None),
                'credits': account.credit_wallet.prepaid_balance if hasattr(account, 'credit_wallet') else 0})
        return Response({'results': rows, 'count': len(rows)})


class CancelSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        account = ensure_account(request.user)
        sub = Subscription.objects.filter(account=account, status=Subscription.Status.ACTIVE).order_by('-starts_at').first()
        if not sub:
            return Response({'detail': 'No active paid subscription can be cancelled.'}, status=400)
        sub.status = Subscription.Status.CANCEL_AT_PERIOD_END
        sub.cancel_at_period_end = True
        sub.cancelled_at = timezone.now()
        sub.save(update_fields=['status', 'cancel_at_period_end', 'cancelled_at', 'updated_at'])
        BillingAuditLog.objects.create(actor=request.user, account=account, action='subscription_cancel_scheduled',
            object_type='Subscription', object_id=str(sub.pk), details={'effective_at': sub.current_period_end.isoformat() if sub.current_period_end else None})
        return Response({'status': sub.status, 'effective_at': sub.current_period_end})


class InvoiceDownloadView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, invoice_id):
        invoice = Invoice.objects.filter(pk=invoice_id, owner=request.user,
            transaction__status=PaymentTransaction.Status.CAPTURED,
            transaction__verified_at__isnull=False).first()
        if not invoice:
            return Response({'detail': 'Receipt not found.'}, status=404)
        from decimal import Decimal
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        pdf.setTitle(f'Payment receipt {invoice.invoice_number}')
        pdf.setFont('Helvetica-Bold', 18)
        pdf.drawString(48, 790, 'Scholivyn payment receipt')
        pdf.setFont('Helvetica', 11)
        lines = [f'Receipt: {invoice.invoice_number}', f'Issued: {invoice.issued_at:%Y-%m-%d %H:%M UTC}',
            f'Customer: {invoice.owner.email}', f'Description: {invoice.description}',
            f'Amount: {Decimal(invoice.amount_minor) / Decimal(100):.2f} {invoice.currency}',
            f'Tax recorded: {Decimal(invoice.tax_minor) / Decimal(100):.2f} {invoice.currency}',
            'This receipt is not a statutory tax invoice.']
        y = 752
        for line in lines:
            pdf.drawString(48, y, line[:180]); y -= 24
        pdf.showPage(); pdf.save()
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{invoice.invoice_number}.pdf"'
        response['Cache-Control'] = 'private, no-store'
        return response
