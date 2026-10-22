"""Hodnoty dostupné ve všech šablonách."""

from django.conf import settings


def demo_mode(request):
    return {"demo_mode": settings.DEMO_MODE}


def read_only(request):
    """Výzkumník jen čte – stránky to řeknou předem, ne až po pokusu uložit."""
    from .middleware import PORTAL_HOME, READ_ONLY

    user = getattr(request, "user", None)
    logged = bool(user and user.is_authenticated and not user.is_superuser)
    return {"read_only": logged and user.role in READ_ONLY,
            # portál sportovce/trenéra má vlastní menu, bez hledání a laboratorních akcí
            "portal": logged and user.role in PORTAL_HOME}


def booking_counts(request):
    """Počet nových objednávek do menu – jen pro ty, kdo je vyřizují."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.sees_identity:
        return {}
    from apps.booking.models import BookingRequest

    return {"nove_objednavky": BookingRequest.objects.for_user(user)
            .filter(status=BookingRequest.Status.NEW).count()}
