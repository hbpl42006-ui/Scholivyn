from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.billing.models import (
    BillingAccount, BillingAuditLog, CreditLedgerEntry, CreditReservation,
    CreditWallet, Subscription, SubscriptionPlan, UsageEvent,
)

MAX_STORED_INTEGER = (1 << 63) - 1


class BillingError(Exception):
    pass


class FeatureUnavailable(BillingError):
    pass


class InsufficientCredits(BillingError):
    pass


def ensure_account(user):
    """Create safe, zero-priced account records lazily for legacy users."""
    account, _ = BillingAccount.objects.get_or_create(
        owner=user, defaults={'billing_email': user.email, 'display_name': getattr(user, 'full_name', '')}
    )
    CreditWallet.objects.get_or_create(account=account)
    now = timezone.now()
    Subscription.objects.filter(account=account, status__in=[Subscription.Status.TRIALING,
        Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE,
        Subscription.Status.CANCEL_AT_PERIOD_END], current_period_end__lte=now).update(
            status=Subscription.Status.EXPIRED, cancel_at_period_end=False, updated_at=now)
    active = Subscription.objects.filter(account=account, status__in=[Subscription.Status.FREE,
        Subscription.Status.TRIALING, Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE,
        Subscription.Status.CANCEL_AT_PERIOD_END]).exists()
    free = SubscriptionPlan.objects.filter(tier=SubscriptionPlan.Tier.FREE, revision=1).first()
    if free and not active:
        Subscription.objects.get_or_create(account=account, status=Subscription.Status.FREE,
            defaults={'plan': free, 'starts_at': timezone.now(), 'current_period_start': timezone.now(),
                      'current_period_end': None})
    return account


def current_subscription(account):
    now = timezone.now()
    return (Subscription.objects.filter(account=account, starts_at__lte=now,
        status__in=[Subscription.Status.FREE, Subscription.Status.TRIALING,
                    Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE,
                    Subscription.Status.CANCEL_AT_PERIOD_END])
        .filter(Q(current_period_end__isnull=True) | Q(current_period_end__gt=now))
        .order_by('-starts_at').select_related('plan', 'price').first())


@transaction.atomic
def reserve_usage(user, *, feature, idempotency_key, units=1, reference_type='', reference_id=''):
    """Reserve configured usage before work. Enforcement is opt-in until plans are configured."""
    if not settings.BILLING_ENFORCEMENT_ENABLED:
        return None
    if units < 1 or units > MAX_STORED_INTEGER or not idempotency_key:
        raise BillingError('A positive unit count and idempotency key are required.')
    account = BillingAccount.objects.select_for_update().get(pk=ensure_account(user).pk)
    existing = CreditReservation.objects.filter(account=account, idempotency_key=idempotency_key).first()
    if existing:
        if existing.feature != feature or existing.reserved_units != units:
            raise BillingError('Idempotency key was already used for different work.')
        return existing
    sub = current_subscription(account)
    if not sub or not sub.plan.available:
        raise FeatureUnavailable('No active plan is configured for this account.')
    if sub.plan.feature_entitlements.get(feature) is not True:
        raise FeatureUnavailable(f'The current plan does not include {feature}.')
    start = sub.current_period_start
    quota = int(sub.plan.monthly_quotas.get(feature, 0))
    used = UsageEvent.objects.filter(account=account, feature=feature, measured_at__gte=start).aggregate(n=Sum('units'))['n'] or 0
    held = CreditReservation.objects.filter(account=account, feature=feature, status=CreditReservation.Status.RESERVED,
        created_at__gte=start).aggregate(n=Sum('included_units'))['n'] or 0
    included = min(units, max(0, quota - used - held))
    overage = units - included
    cost = int(sub.plan.credit_costs.get(feature, 0))
    credits = overage * cost
    if credits > MAX_STORED_INTEGER:
        raise BillingError('Requested usage is above the supported billing limit.')
    wallet = CreditWallet.objects.select_for_update().get(account=account)
    if wallet.prepaid_balance < credits:
        raise InsufficientCredits('There are not enough prepaid credits for this request.')
    if credits:
        changed = CreditWallet.objects.filter(pk=wallet.pk, prepaid_balance__gte=credits).update(prepaid_balance=F('prepaid_balance') - credits)
        if not changed:
            raise InsufficientCredits('There are not enough prepaid credits for this request.')
        balance = wallet.prepaid_balance - credits
        CreditLedgerEntry.objects.create(account=account, kind=CreditLedgerEntry.Kind.RESERVATION,
            direction='debit', amount=credits, balance_after=balance,
            idempotency_key=f'reserve:{account.pk}:{idempotency_key}', reference_type=reference_type,
            reference_id=reference_id)
    else:
        balance = wallet.prepaid_balance
    return CreditReservation.objects.create(account=account, owner=user, feature=feature,
        idempotency_key=idempotency_key, reserved_units=units, included_units=included,
        credits_reserved=credits, credit_cost_per_unit=cost, reference_type=reference_type,
        reference_id=reference_id, expires_at=timezone.now() + timedelta(hours=2))


@transaction.atomic
def mark_provider_started(reservation):
    if reservation:
        CreditReservation.objects.filter(pk=reservation.pk, status=CreditReservation.Status.RESERVED,
            provider_started_at__isnull=True).update(provider_started_at=timezone.now())


@transaction.atomic
def finalize_usage(reservation, *, event_key, units=1, input_tokens=0, output_tokens=0,
                   reasoning_tokens=None, storage_bytes=0, provider_cost_minor=None,
                   provider_cost_currency='', details=None):
    if reservation is None:
        return None
    reservation = CreditReservation.objects.select_for_update().select_related('account').get(pk=reservation.pk)
    found = UsageEvent.objects.filter(event_key=event_key).first()
    if found:
        return found
    if reservation.status == CreditReservation.Status.CONSUMED:
        raise BillingError('Reservation was already finalized with another event key.')
    if reservation.status != CreditReservation.Status.RESERVED:
        raise BillingError('Reservation is not available for settlement.')
    if units < 0 or units > reservation.reserved_units:
        raise BillingError('Measured usage exceeds its reservation.')
    actual_overage = max(0, units - reservation.included_units)
    charged = min(reservation.credits_reserved, actual_overage * reservation.credit_cost_per_unit)
    refund = reservation.credits_reserved - charged
    if refund:
        wallet = CreditWallet.objects.select_for_update().get(account=reservation.account)
        if wallet.prepaid_balance + refund > MAX_STORED_INTEGER:
            raise BillingError('Credit refund exceeds the supported wallet balance.')
        wallet.prepaid_balance += refund
        wallet.save(update_fields=['prepaid_balance', 'updated_at'])
        CreditLedgerEntry.objects.create(account=reservation.account, kind=CreditLedgerEntry.Kind.REFUND,
            direction='credit', amount=refund, balance_after=wallet.prepaid_balance,
            idempotency_key=f'refund:{reservation.pk}', reference_type=reservation.reference_type,
            reference_id=reservation.reference_id)
    reservation.status = CreditReservation.Status.CONSUMED
    reservation.finalized_at = timezone.now()
    reservation.save(update_fields=['status', 'finalized_at'])
    return UsageEvent.objects.create(owner=reservation.owner, account=reservation.account,
        reservation=reservation, event_key=event_key, feature=reservation.feature, units=units,
        input_tokens=input_tokens, output_tokens=output_tokens, reasoning_tokens=reasoning_tokens,
        storage_bytes=storage_bytes,
        credits_debited=charged, provider_cost_minor=provider_cost_minor,
        provider_cost_currency=provider_cost_currency, reference_type=reservation.reference_type,
        reference_id=reservation.reference_id, measured_at=timezone.now(), details=details or {})


@transaction.atomic
def release_reservation(reservation, *, uncertain=False):
    if not reservation:
        return
    item = CreditReservation.objects.select_for_update().get(pk=reservation.pk)
    if item.status != CreditReservation.Status.RESERVED:
        return
    # Once a request may have reached a provider, retain the reserve until reconciliation.
    if uncertain or item.provider_started_at:
        item.status = CreditReservation.Status.UNCERTAIN
        item.save(update_fields=['status'])
        return
    if item.credits_reserved:
        wallet = CreditWallet.objects.select_for_update().get(account=item.account)
        if wallet.prepaid_balance + item.credits_reserved > MAX_STORED_INTEGER:
            raise BillingError('Credit release exceeds the supported wallet balance.')
        wallet.prepaid_balance += item.credits_reserved
        wallet.save(update_fields=['prepaid_balance', 'updated_at'])
        CreditLedgerEntry.objects.create(account=item.account, kind=CreditLedgerEntry.Kind.REFUND,
            direction='credit', amount=item.credits_reserved, balance_after=wallet.prepaid_balance,
            idempotency_key=f'release:{item.pk}', reference_type=item.reference_type,
            reference_id=item.reference_id)
    item.status = CreditReservation.Status.RELEASED
    item.finalized_at = timezone.now()
    item.save(update_fields=['status', 'finalized_at'])
