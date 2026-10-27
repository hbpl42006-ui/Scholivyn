from django.contrib import admin
from apps.billing.models import (BillingAccount, BillingAuditLog, CreditLedgerEntry, CreditPack,
    CreditReservation, CreditWallet, Invoice, PaymentOrder, PaymentTransaction,
    PlanPrice, Subscription, SubscriptionPlan, UsageEvent, WebhookEvent)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'tier', 'revision', 'available', 'trial_enabled', 'created_at')
    list_filter = ('tier', 'available', 'trial_enabled')
    search_fields = ('name', 'code', 'description')
    readonly_fields = ('created_at',)


@admin.register(PlanPrice)
class PlanPriceAdmin(admin.ModelAdmin):
    list_display = ('plan', 'interval', 'amount_minor', 'currency', 'available', 'effective_from', 'effective_until')
    list_filter = ('interval', 'currency', 'available')
    search_fields = ('plan__name', 'plan__code')
    readonly_fields = ('created_at',)


@admin.register(CreditPack)
class CreditPackAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'revision', 'amount_minor', 'currency', 'credits', 'available', 'effective_from')
    list_filter = ('currency', 'available')
    search_fields = ('name', 'code')
    readonly_fields = ('created_at',)


@admin.register(BillingAccount)
class BillingAccountAdmin(admin.ModelAdmin):
    list_display = ('owner', 'billing_email', 'customer_reference', 'created_at')
    search_fields = ('owner__email', 'owner__username', 'billing_email', 'customer_reference')
    readonly_fields = ('customer_reference', 'created_at', 'updated_at')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('account', 'plan', 'status', 'starts_at', 'current_period_end')
    list_filter = ('status', 'plan__tier')
    search_fields = ('account__owner__email', 'account__owner__username')
    readonly_fields = tuple(f.name for f in Subscription._meta.fields)
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'provider', 'purpose', 'amount_minor', 'currency', 'status', 'created_at')
    list_filter = ('provider', 'purpose', 'status', 'currency')
    search_fields = ('owner__email', 'provider_order_id', 'id')
    readonly_fields = tuple(f.name for f in PaymentOrder._meta.fields)
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ('provider_payment_id', 'order', 'status', 'amount_minor', 'currency', 'verified_at')
    list_filter = ('status', 'currency')
    search_fields = ('provider_payment_id', 'order__owner__email')
    readonly_fields = tuple(f.name for f in PaymentTransaction._meta.fields)
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


for model in (CreditWallet, CreditLedgerEntry, CreditReservation, UsageEvent, WebhookEvent, Invoice, BillingAuditLog):
    admin.site.register(model, ReadOnlyAdmin)
