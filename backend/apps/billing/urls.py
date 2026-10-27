from django.urls import path
from apps.billing import views

urlpatterns = [
    path('billing/', views.BillingOverviewView.as_view(), name='billing-overview'),
    path('billing/plans/', views.PlanListView.as_view(), name='billing-plans'),
    path('billing/credit-packs/', views.CreditPackListView.as_view(), name='billing-credit-packs'),
    path('billing/history/', views.BillingHistoryView.as_view(), name='billing-history'),
    path('billing/orders/', views.CreateOrderView.as_view(), name='billing-create-order'),
    path('billing/verify-checkout/', views.VerifyCheckoutView.as_view(), name='billing-verify-checkout'),
    path('billing/subscription/cancel/', views.CancelSubscriptionView.as_view(), name='billing-cancel-subscription'),
    path('billing/invoices/<int:invoice_id>/download/', views.InvoiceDownloadView.as_view(), name='billing-invoice-download'),
    path('billing/webhooks/razorpay/', views.RazorpayWebhookView.as_view(), name='billing-razorpay-webhook'),
    path('billing/admin/summary/', views.AdminBillingSummaryView.as_view(), name='billing-admin-summary'),
    path('billing/admin/customers/', views.AdminCustomerLookupView.as_view(), name='billing-admin-customers'),
]
