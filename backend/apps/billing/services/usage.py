from apps.billing.models import CreditReservation
from apps.billing.services.entitlements import (BillingError, FeatureUnavailable,
    InsufficientCredits, finalize_usage, release_reservation, reserve_usage)


def billing_http_status(error):
    if isinstance(error, FeatureUnavailable):
        return 403
    if isinstance(error, InsufficientCredits):
        return 402
    return 409


def settle_job(feature, reference_type, reference_id, *, success, units=1,
               input_tokens=0, output_tokens=0, reasoning_tokens=None, uncertain=False):
    reservation = CreditReservation.objects.filter(feature=feature, reference_type=reference_type,
        reference_id=str(reference_id)).first()
    if not reservation:
        return
    if success:
        finalize_usage(reservation, event_key=f'{feature}:{reference_type}:{reference_id}',
            units=units, input_tokens=input_tokens, output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens)
    else:
        release_reservation(reservation, uncertain=uncertain)
