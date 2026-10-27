import hashlib
import hmac
import json
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class PaymentError(Exception):
    pass


def verify_checkout_signature(order_id, payment_id, signature, secret):
    if not all(isinstance(v, str) and v for v in (order_id, payment_id, signature, secret)):
        return False
    expected = hmac.new(secret.encode(), f'{order_id}|{payment_id}'.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body, signature, secret):
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def razorpay_fetch_payment(payment_id):
    """Fetch authoritative payment state; network access only in explicit Razorpay test mode."""
    if settings.PAYMENT_MODE != 'razorpay_test':
        raise PaymentError('Razorpay test mode is not enabled.')
    key = settings.RAZORPAY_KEY_ID
    secret = settings.RAZORPAY_KEY_SECRET
    if not key.startswith('rzp_test_') or not secret:
        raise ImproperlyConfigured('Razorpay test credentials are not configured.')
    if not payment_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in payment_id):
        raise PaymentError('Invalid payment identifier.')
    request = urllib.request.Request(
        f'https://api.razorpay.com/v1/payments/{payment_id}',
        headers={'Authorization': 'Basic ' + __import__('base64').b64encode(f'{key}:{secret}'.encode()).decode(),
                 'Accept': 'application/json'}, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read(65536))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        # Do not attach provider body or credentials to the error.
        raise PaymentError('Payment verification is temporarily unavailable.') from exc
    if not isinstance(payload, dict):
        raise PaymentError('Payment provider returned an invalid response.')
    return payload


def verified_amount_matches(payment, order, *, expected_payment_id=None):
    return (payment.get('status') == 'captured'
            and (expected_payment_id is None or payment.get('id') == expected_payment_id)
            and payment.get('order_id') == order.provider_order_id
            and payment.get('amount') == order.amount_minor
            and payment.get('currency') == order.currency)
