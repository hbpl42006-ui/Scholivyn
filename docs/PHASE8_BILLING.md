# Phase 8 billing foundation

## Safe defaults and rollout

Billing is opt-in. `PAYMENT_MODE=mock`, `BILLING_ENFORCEMENT_ENABLED=false`, and `SUBSCRIPTION_RENEWALS_ENABLED=false` are the defaults. Mock orders remain pending and never activate a subscription. Plans are seeded as unavailable categories with empty entitlements, quotas, prices, and credit costs. Administrators must decide the product policy and configure those values before publishing plans or enabling enforcement. No historical AI usage is charged retroactively. Legacy customers receive a zero-price Free subscription lazily when their billing account is first accessed.

The migrations `billing.0001_initial` and `billing.0002_creditpack_paymentorder_credit_pack` create billing tables, unavailable plan categories, and configurable prepaid credit packs. Review them, back up the target database, then apply them explicitly during a planned deployment. This implementation has not applied migrations to the existing local SQLite database.

## Configuration

For local development, use the root `.env` only for the allowlisted billing settings below. The Windows settings loader deliberately ignores `POSTGRES_*`, `REDIS_URL`, and Docker service names. Never commit populated `.env` files.

```dotenv
PAYMENT_MODE=mock
BILLING_ENFORCEMENT_ENABLED=false
SUBSCRIPTION_RENEWALS_ENABLED=false
# Only after configuring a Razorpay test account:
PAYMENT_MODE=razorpay_test
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=<secret-manager value>
RAZORPAY_WEBHOOK_SECRET=<separate webhook secret>
```

The test adapter is restricted to Razorpay's fixed HTTPS API host and `rzp_test_` key IDs. No live mode is implemented. Checkout signatures are verified server-side and captured state, order id, amount, and currency are fetched from the provider before activation. Webhook HMAC uses the exact raw request body. Do not expose the secret or webhook secret in browser code.

## Credit policy

Money is stored in integer minor units. Credits are integer units. `CreditLedgerEntry` is append-only; refunds and adjustments are compensating entries. Reservation calls require an idempotency key and configured feature entitlement, use database transactions and balance guards, and keep provider-started ambiguous requests in `uncertain` state. Feature keys are `ai_review`, `similarity_comparison`, `citation_analysis`, `journal_recommendation`, and `document_storage` (storage quotas are measured in bytes). AI review uses its existing job identifier as the idempotency reference and settles recorded input/output/reasoning token usage once. Quota reservations are finalized only after work ends; queued quota waits retain the reservation. Customers are never charged for opening existing results.

Provider API quotas and customer plan quotas are separate. Provider-cost values are populated only when actual measured provider-cost inputs are supplied; the system does not estimate or fabricate revenue. Statutory tax invoice issuance is disabled. PDF downloads are payment receipts and explicitly not statutory tax invoices. Refund processing and automatic recurring debits are not enabled.

## API and UI

Authenticated BFF paths are under `/api/research/billing/`: account overview, plans, credit packs, history, order creation, checkout verification, cancellation, and owned receipt download. Razorpay webhook verification is signature-authenticated at `/api/v1/billing/webhooks/razorpay/`. Staff metrics and customer lookup are server-enforced with `IsAdminUser`; frontend visibility is not authorization. Plan, price, and credit-pack configuration uses Django Admin and immutable revisions. Customer routes are `/dashboard/billing`, `/plans`, `/usage`, `/history`, and `/settings`; the staff summary and customer lookup are at `/dashboard/admin/billing`.

## Apply and check safely

From `F:\Scholivyn\backend`, first take a consistent backup and inspect pending migrations:

```powershell
python manage.py showmigrations
python manage.py sqlmigrate billing 0001
python manage.py migrate --plan
```

Only after database-owner approval and backup, apply explicitly with `python manage.py migrate billing`. Note the project-level Docker Compose backend currently runs `python manage.py migrate` on container startup, so review that command before pointing it at any existing production database. The coding/CI tests use disposable test databases; implementation validation did not apply this migration to `db.sqlite3`.

For test mode, configure Razorpay test credentials in the secret manager/environment, start Django, set a test webhook URL with the exact HTTPS staging endpoint, and perform one low-value test transaction. Reconcile the stored PaymentOrder, verified PaymentTransaction, receipt, and subscription before any further testing. No live charges were performed during implementation.

## Known limits before production

- Financial and pricing policy, tax/legal merchant details, customer-support/refund workflow, and plan entitlements remain administrator/business decisions.
- Automatic renewals, Cashfree, live Razorpay, automated reconciliation jobs, refund API calls, email notices, and historical usage backfills are not implemented.
- Paid-plan changes are intentionally blocked until the active period ends; scheduled upgrades/downgrades and pending subscription-order expiry/reconciliation remain open lifecycle work.
- The staff dashboard exposes verified revenue/plan counts, order state, notices, recorded AI costs, and customer lookup. Audited manual credit adjustment, automated reconciliation, and deeper worker-health integrations remain future work.
- AI analysis, similarity comparisons, citation analysis, journal recommendations, and document storage reserve against configured account quotas at their creation/processing boundaries. External citation-metadata lookups are not individually metered, and workable quota/price policies still require business configuration.
- Credit packs use immutable, effective-dated integer-minor-unit pricing and grant credits only after verified capture.
- Redis/Celery recovery and real staging payment webhooks were not exercised in this implementation.
