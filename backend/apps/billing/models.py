import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('Financial history is immutable; create a compensating record instead.')

    def delete(self):
        raise ValidationError('Financial history cannot be deleted.')


ImmutableManager = models.Manager.from_queryset(ImmutableQuerySet)


class SubscriptionPlan(models.Model):
    class Tier(models.TextChoices):
        FREE = 'free', 'Free'
        PRO = 'pro', 'Pro'
        TEAM = 'team', 'Team'

    tier = models.CharField(max_length=12, choices=Tier.choices, db_index=True)
    code = models.SlugField(max_length=60)
    name = models.CharField(max_length=100)
    revision = models.PositiveIntegerField(default=1)
    description = models.CharField(max_length=500, blank=True)
    available = models.BooleanField(default=False)
    feature_entitlements = models.JSONField(default=dict, blank=True)
    monthly_quotas = models.JSONField(default=dict, blank=True)
    credit_costs = models.JSONField(default=dict, blank=True)
    trial_enabled = models.BooleanField(default=False)
    trial_days = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('tier', 'name', '-revision')
        constraints = [models.UniqueConstraint(fields=('code', 'revision'), name='bill_plan_code_rev_uq')]

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            terms = ('tier', 'code', 'name', 'revision', 'description', 'feature_entitlements',
                     'monthly_quotas', 'credit_costs', 'trial_enabled', 'trial_days')
            if any(getattr(previous, field) != getattr(self, field) for field in terms):
                raise ValidationError('Plan terms are revisioned and immutable. Create a new plan revision.')
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} r{self.revision}'


class PlanPrice(models.Model):
    class Interval(models.TextChoices):
        MONTHLY = 'monthly', 'Monthly'
        ANNUAL = 'annual', 'Annual'

    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='prices')
    interval = models.CharField(max_length=12, choices=Interval.choices)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default='INR')
    available = models.BooleanField(default=False)
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('plan__tier', 'interval', '-effective_from')
        indexes = [models.Index(fields=('plan', 'available', 'interval'))]
        constraints = [models.CheckConstraint(condition=Q(amount_minor__gte=0), name='bill_price_nonnegative')]

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            immutable = ('plan_id', 'interval', 'amount_minor', 'currency', 'effective_from')
            if any(getattr(previous, field) != getattr(self, field) for field in immutable):
                raise ValidationError('Price terms are immutable. Create a new effective-dated price instead.')
        return super().save(*args, **kwargs)


class CreditPack(models.Model):
    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=100)
    revision = models.PositiveIntegerField(default=1)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default='INR')
    credits = models.PositiveBigIntegerField()
    available = models.BooleanField(default=False)
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('name', '-revision')
        constraints = [models.CheckConstraint(condition=Q(amount_minor__gt=0), name='bill_pack_amount_positive'),
                       models.CheckConstraint(condition=Q(credits__gt=0), name='bill_pack_credits_positive')]

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            terms = ('code', 'name', 'revision', 'amount_minor', 'currency', 'credits', 'effective_from')
            if any(getattr(old, f) != getattr(self, f) for f in terms):
                raise ValidationError('Credit pack terms are immutable. Create a new revision.')
        return super().save(*args, **kwargs)


class BillingAccount(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='billing_account')
    customer_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    billing_email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Billing account {self.customer_reference}'


class Subscription(models.Model):
    class Status(models.TextChoices):
        FREE = 'free', 'Free'
        TRIALING = 'trialing', 'Trialing'
        ACTIVE = 'active', 'Active'
        PAST_DUE = 'past_due', 'Past due'
        CANCEL_AT_PERIOD_END = 'cancel_at_period_end', 'Cancels at period end'
        CANCELLED = 'cancelled', 'Cancelled'
        EXPIRED = 'expired', 'Expired'

    account = models.ForeignKey(BillingAccount, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name='subscriptions')
    price = models.ForeignKey(PlanPrice, null=True, blank=True, on_delete=models.PROTECT, related_name='subscriptions')
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.FREE, db_index=True)
    starts_at = models.DateTimeField()
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    gateway_reference = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-starts_at',)
        indexes = [models.Index(fields=('account', 'status', 'current_period_end'))]
        constraints = [models.UniqueConstraint(fields=('account',), condition=Q(status__in=('free', 'trialing', 'active', 'past_due', 'cancel_at_period_end')), name='bill_one_current_sub_uq')]


class CreditWallet(models.Model):
    account = models.OneToOneField(BillingAccount, on_delete=models.CASCADE, related_name='credit_wallet')
    prepaid_balance = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(prepaid_balance__gte=0), name='bill_wallet_nonnegative')]


class CreditLedgerEntry(models.Model):
    class Kind(models.TextChoices):
        PURCHASE = 'purchase', 'Purchase'
        RESERVATION = 'reservation', 'Reservation'
        REFUND = 'refund', 'Refund'
        ADMIN_GRANT = 'admin_grant', 'Administrator grant'
        ADMIN_DEBIT = 'admin_debit', 'Administrator debit'
        REVERSAL = 'reversal', 'Reversal'

    account = models.ForeignKey(BillingAccount, on_delete=models.PROTECT, related_name='credit_ledger')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    direction = models.CharField(max_length=8, choices=(('credit', 'Credit'), ('debit', 'Debit')))
    amount = models.PositiveBigIntegerField()
    balance_after = models.PositiveBigIntegerField()
    idempotency_key = models.CharField(max_length=180, unique=True)
    reference_type = models.CharField(max_length=40, blank=True)
    reference_id = models.CharField(max_length=80, blank=True)
    description = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='billing_ledger_actions')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    objects = ImmutableManager()

    class Meta:
        ordering = ('-created_at', '-pk')
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='bill_ledger_amount_positive')]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Credit ledger entries are immutable; record a compensating entry.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Credit ledger entries cannot be deleted.')


class CreditReservation(models.Model):
    class Status(models.TextChoices):
        RESERVED = 'reserved', 'Reserved'
        CONSUMED = 'consumed', 'Consumed'
        RELEASED = 'released', 'Released'
        UNCERTAIN = 'uncertain', 'Needs reconciliation'

    account = models.ForeignKey(BillingAccount, on_delete=models.PROTECT, related_name='reservations')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='credit_reservations')
    feature = models.CharField(max_length=48, db_index=True)
    idempotency_key = models.CharField(max_length=180)
    reserved_units = models.PositiveBigIntegerField(default=1)
    included_units = models.PositiveBigIntegerField(default=0)
    credits_reserved = models.PositiveBigIntegerField(default=0)
    credit_cost_per_unit = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RESERVED, db_index=True)
    reference_type = models.CharField(max_length=40, blank=True)
    reference_id = models.CharField(max_length=80, blank=True)
    provider_started_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('account', 'idempotency_key'), name='bill_res_account_key_uq')]
        indexes = [models.Index(fields=('owner', 'feature', 'status'))]


class UsageEvent(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='billing_usage_events')
    account = models.ForeignKey(BillingAccount, on_delete=models.PROTECT, related_name='usage_events')
    reservation = models.OneToOneField(CreditReservation, null=True, blank=True, on_delete=models.PROTECT, related_name='usage_event')
    event_key = models.CharField(max_length=180, unique=True)
    feature = models.CharField(max_length=48, db_index=True)
    units = models.PositiveBigIntegerField(default=1)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    reasoning_tokens = models.PositiveBigIntegerField(null=True, blank=True)
    storage_bytes = models.PositiveBigIntegerField(default=0)
    credits_debited = models.PositiveBigIntegerField(default=0)
    provider_cost_minor = models.PositiveBigIntegerField(null=True, blank=True)
    provider_cost_currency = models.CharField(max_length=3, blank=True)
    reference_type = models.CharField(max_length=40, blank=True)
    reference_id = models.CharField(max_length=80, blank=True)
    measured_at = models.DateTimeField(db_index=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('-measured_at',)
        indexes = [models.Index(fields=('account', 'feature', 'measured_at'))]


class PaymentOrder(models.Model):
    class Status(models.TextChoices):
        CREATED = 'created', 'Created'
        PENDING = 'pending', 'Pending'
        PAID = 'paid', 'Paid'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'
        REFUNDED = 'refunded', 'Refunded'

    class Purpose(models.TextChoices):
        SUBSCRIPTION = 'subscription', 'Subscription'
        CREDIT_TOPUP = 'credit_topup', 'Credit top-up'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='billing_orders')
    account = models.ForeignKey(BillingAccount, on_delete=models.PROTECT, related_name='payment_orders')
    plan_price = models.ForeignKey(PlanPrice, null=True, blank=True, on_delete=models.PROTECT, related_name='orders')
    credit_pack = models.ForeignKey(CreditPack, null=True, blank=True, on_delete=models.PROTECT, related_name='orders')
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    provider = models.CharField(max_length=20, default='mock')
    provider_order_id = models.CharField(max_length=120, blank=True, db_index=True)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default='INR')
    credits_to_grant = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED, db_index=True)
    idempotency_key = models.CharField(max_length=180)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(fields=('owner', 'idempotency_key'), name='bill_order_owner_key_uq'),
            models.CheckConstraint(condition=Q(amount_minor__gt=0), name='bill_order_amount_positive'),
        ]
        indexes = [models.Index(fields=('account', 'status', 'created_at'))]


class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        AUTHORIZED = 'authorized', 'Authorized'
        CAPTURED = 'captured', 'Captured'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'

    order = models.ForeignKey(PaymentOrder, on_delete=models.PROTECT, related_name='transactions')
    provider_payment_id = models.CharField(max_length=120, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    verified_at = models.DateTimeField(null=True, blank=True)
    refunded_minor = models.PositiveBigIntegerField(default=0)
    provider_reference = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = ImmutableManager()

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Payment transactions are immutable; record a compensating refund transaction.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Payment transactions cannot be deleted.')


class WebhookEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED = 'received', 'Received'
        PROCESSED = 'processed', 'Processed'
        IGNORED = 'ignored', 'Ignored'
        FAILED = 'failed', 'Failed'

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=180)
    event_type = models.CharField(max_length=80)
    payload_sha256 = models.CharField(max_length=64)
    signature_valid = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    error_category = models.CharField(max_length=40, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('provider', 'event_id'), name='bill_webhook_provider_id_uq')]


class Invoice(models.Model):
    class Status(models.TextChoices):
        RECEIPT = 'receipt', 'Payment receipt'
        VOID = 'void', 'Void'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='billing_invoices')
    account = models.ForeignKey(BillingAccount, on_delete=models.PROTECT, related_name='invoices')
    transaction = models.OneToOneField(PaymentTransaction, on_delete=models.PROTECT, related_name='invoice')
    invoice_number = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RECEIPT)
    amount_minor = models.PositiveBigIntegerField()
    tax_minor = models.PositiveBigIntegerField(default=0)
    currency = models.CharField(max_length=3)
    description = models.CharField(max_length=240)
    issued_at = models.DateTimeField()
    statutory_tax_invoice = models.BooleanField(default=False)
    objects = ImmutableManager()

    class Meta:
        ordering = ('-issued_at',)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Issued receipts are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Issued receipts cannot be deleted.')


class BillingAuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='billing_audit_actions')
    account = models.ForeignKey(BillingAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs')
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=100)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-created_at',)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Billing audit records are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Billing audit entries cannot be deleted.')
