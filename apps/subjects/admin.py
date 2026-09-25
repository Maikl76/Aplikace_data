from django.contrib import admin, messages
from django.db.models import ProtectedError

from .models import Consent, Sport, Subject, SubjectExternalId, SubjectIdentity, Team


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "sport", "organization")
    list_filter = ("sport",)


class ConsentInline(admin.TabularInline):
    model = Consent
    extra = 0


class ExternalIdInline(admin.TabularInline):
    """Jak sportovce znají přístroje – import ho podle toho pozná."""

    model = SubjectExternalId
    extra = 0
    fields = ("system", "value")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "sport", "team", "sex", "birth_year", "level",
                    "pocet_mereni", "is_active")
    list_filter = ("sport", "team", "sex", "level", "is_active")
    search_fields = ("code",)
    inlines = [ConsentInline, ExternalIdInline]
    actions = ["deaktivovat", "aktivovat"]

    @admin.display(description="testovacích dnů")
    def pocet_mereni(self, obj):
        return obj.sessions.count()

    @admin.action(description="Deaktivovat (skryje ze seznamů, data zůstanou)")
    def deaktivovat(self, request, queryset):
        pocet = queryset.update(is_active=False)
        self.message_user(request, f"Deaktivováno {pocet} sportovců. "
                                   f"Naměřená data zůstala zachovaná.")

    @admin.action(description="Aktivovat")
    def aktivovat(self, request, queryset):
        pocet = queryset.update(is_active=True)
        self.message_user(request, f"Aktivováno {pocet} sportovců.")

    def delete_model(self, request, obj):
        """
        Sportovce s naměřenými daty databáze smazat nedovolí – vazby jsou
        chráněné, aby se longitudinální data neztratila omylem. Místo
        nesrozumitelné chyby to řekneme srozumitelně.
        """
        try:
            super().delete_model(request, obj)
        except ProtectedError:
            self.message_user(
                request,
                f"Sportovce {obj.code} nelze smazat – má {obj.sessions.count()} "
                f"testovacích dnů s naměřenými daty. Použijte „Deaktivovat“. "
                f"Pokud jde o výmaz podle GDPR, smažte jeho identitu "
                f"(Identity sportovců); měření pak zůstanou anonymní.",
                level=messages.ERROR,
            )

    def delete_queryset(self, request, queryset):
        smazano, blokovano = 0, []
        for obj in queryset:
            try:
                obj.delete()
                smazano += 1
            except ProtectedError:
                blokovano.append(obj.code)
        if smazano:
            self.message_user(request, f"Smazáno {smazano} sportovců bez měření.")
        if blokovano:
            self.message_user(
                request,
                f"Nešlo smazat (mají naměřená data): {', '.join(blokovano)}. "
                f"Použijte „Deaktivovat“.",
                level=messages.ERROR,
            )


@admin.register(Consent)
class ConsentAdmin(admin.ModelAdmin):
    list_display = ("subject", "scope", "granted_on", "valid_until",
                    "revoked_on", "plati")
    list_filter = ("scope", "granted_on")
    search_fields = ("subject__code",)
    date_hierarchy = "granted_on"

    @admin.display(description="platí", boolean=True)
    def plati(self, obj):
        return obj.is_valid

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("subject")


@admin.register(SubjectIdentity)
class SubjectIdentityAdmin(admin.ModelAdmin):
    """Identita je citlivá – v administraci jen pro superuživatele."""

    list_display = ("subject", "created_at")
    search_fields = ("subject__code",)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser
