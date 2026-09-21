"""Zápis do auditu. Volá se odtud, aby byl formát jednotný."""

from .models import AuditLog


def record(request, action, obj, *, subject_code="", **detail):
    return AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(getattr(obj, "pk", "")),
        subject_code=subject_code,
        detail=detail,
        ip_address=request.META.get("REMOTE_ADDR"),
    )
