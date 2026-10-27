import uuid
import calendar

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import (BillingAuditLog, CreditLedgerEntry, CreditWallet, Invoice,
    PaymentOrder, PaymentTransaction, Subscription)
from apps.billing.services.entitlements import MAX_STORED_INTEGER


def _period_end(start, interval):
    month_offset = 12 if interval == 'annual' else 1
    month_index = start.month - 1 + month_offset
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


@transaction.atomic
def record_captured_payment(order, *, payment_id, amount_minor, currency, provider_reference=''):
    order = PaymentOrder.objects.select_for_update().select_related('account', 'plan_price__plan').get(pk=order.pk)
    if amount_minor != order.amount_minor or currency != order.currency:
        raise ValueError('Captured payment does not match order amount/currency.')
    prior = PaymentTransaction.objects.filter(provider_payment_id=payment_id).first()
    if prior:
        if prior.order_id != order.pk or prior.amount_minor != amount_minor or prior.currency != currency:
            raise ValueError('Payment identifier is already associated with different order data.')
        return prior
    if order.status == PaymentOrder.Status.PAID:
        raise ValueError('Order was already paid with a different payment.')
    try:
        with transaction.atomic():
            txn = PaymentTransaction.objects.create(order=order, provider_payment_id=payment_id,
                status=PaymentTransaction.Status.CAPTURED, amount_minor=amount_minor, currency=currency,
                verified_at=timezone.now(), provider_reference=provider_reference[:160])
    except IntegrityError as exc:
        existing = PaymentTransaction.objects.filter(provider_payment_id=payment_id).first()
        if existing and existing.order_id == order.pk and existing.amount_minor == amount_minor and existing.currency == currency:
            return existing
        raise ValueError('Payment identifier is already associated with different order data.') from exc
    order.status = PaymentOrder.Status.PAID
    order.paid_at = timezone.now()
    order.save(update_fields=['status', 'paid_at', 'updated_at'])
    if order.purpose == PaymentOrder.Purpose.SUBSCRIPTION and order.plan_price_id:
        now = timezone.now()
        Subscription.objects.filter(account=order.account,
            status__in=[Subscription.Status.FREE, Subscription.Status.TRIALING,
                        Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE,
                        Subscription.Status.CANCEL_AT_PERIOD_END]).update(
                            status=Subscription.Status.EXPIRED, current_period_end=now)
        Subscription.objects.create(account=order.account, plan=order.plan_price.plan,
            price=order.plan_price, status=Subscription.Status.ACTIVE, starts_at=now,
            current_period_start=now, current_period_end=_period_end(now, order.plan_price.interval))
    elif order.credits_to_grant:
        wallet = CreditWallet.objects.select_for_update().get(account=order.account)
        if wallet.prepaid_balance + order.credits_to_grant > MAX_STORED_INTEGER:
            raise ValueError('Credit purchase exceeds the supported wallet balance.')
        wallet.prepaid_balance += order.credits_to_grant
        wallet.save(update_fields=['prepaid_balance', 'updated_at'])
        CreditLedgerEntry.objects.create(account=order.account, kind=CreditLedgerEntry.Kind.PURCHASE,
            direction='credit', amount=order.credits_to_grant, balance_after=wallet.prepaid_balance,
            idempotency_key=f'purchase:{txn.pk}', reference_type='payment_transaction', reference_id=str(txn.pk))
    Invoice.objects.get_or_create(transaction=txn, defaults={
        'owner': order.owner, 'account': order.account,
        'invoice_number': f'SCH-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}',
        'amount_minor': amount_minor, 'currency': currency,
        'description': 'Payment receipt — not a statutory tax invoice',
        'issued_at': timezone.now(), 'statutory_tax_invoice': False,
    })
    BillingAuditLog.objects.create(actor=order.owner, account=order.account,
        action='payment_captured_verified', object_type='PaymentOrder', object_id=str(order.pk),
        details={'transaction_id': str(txn.pk), 'provider': order.provider})
    return txn
