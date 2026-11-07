"""
Nastavení → Interní reference: z koho se interní referenční hodnoty počítají
(souhlasy), od kolika sportovců se skupina použije, zapnuto / vypnuto, a přehled
skupin (ukazatel × sport × pohlaví × věk) s počtem sportovců a pásmem.
Vysvětluje, že pásmo je interní a necitovatelné a nikdy nejde do zprávy.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.core.audit import record
from apps.core.models import AuditLog, Organization, Role

from .reference import MIN_SUBJECTS_CEILING, MIN_SUBJECTS_FLOOR, ReferenceIndex, reference_steps


def _is_admin(user) -> bool:
    return user.is_superuser or user.role == Role.ADMIN


@login_required
def reference_settings(request):
    user = request.user
    org = user.organization
    if org is None:
        messages.error(request, "Účet nemá pracoviště – přiřadí ho superuživatel v administraci.")
        return redirect("workplace")
    if request.method == "POST":
        if not _is_admin(user):
            return render(request, "core/odepreno.html",
                          {"duvod": "Interní reference nastavuje správce."}, status=403)
        post = request.POST
        try:
            minimum = int(post.get("minimum", org.reference_min_subjects))
        except ValueError:
            minimum = org.reference_min_subjects
        org.reference_min_subjects = max(MIN_SUBJECTS_FLOOR, min(minimum, MIN_SUBJECTS_CEILING))
        source = post.get("zdroj", "")
        if source in Organization.ReferenceSource.values:
            org.reference_source = source
        org.reference_enabled = bool(post.get("zapnuto"))
        org.save(update_fields=["reference_min_subjects", "reference_source", "reference_enabled",
                                "updated_at"])
        record(request, AuditLog.Action.UPDATE, org, nastaveni="interni_reference",
               zdroj=org.reference_source, minimum=org.reference_min_subjects,
               zapnuto=org.reference_enabled)
        messages.success(request, "Nastavení interních referencí je uložené.")
        return redirect("reference_settings")

    index = ReferenceIndex(org)
    rows = index.overview()
    return render(request, "catalog/reference.html", {
        "org": org, "index": index, "rows": rows, "summary": index.summary(),
        "steps": reference_steps(index), "is_admin": _is_admin(user),
        "sources": Organization.ReferenceSource.choices,
        "floor": MIN_SUBJECTS_FLOOR, "ceiling": MIN_SUBJECTS_CEILING,
    })
