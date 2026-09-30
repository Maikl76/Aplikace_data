"""Hodnoty dostupné ve všech šablonách."""

from django.conf import settings


def demo_mode(request):
    return {"demo_mode": settings.DEMO_MODE}


def booking_counts(request):
    """Počet nových objednávek do menu – jen pro ty, kdo je vyřizují."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.sees_identity:
        return {}
    from apps.booking.models import BookingRequest

    return {"nove_objednavky": BookingRequest.objects.for_user(user)
            .filter(status=BookingRequest.Status.NEW).count()}
