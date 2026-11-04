"""
Administrace genetiky: revize karet se dělá tady.

Původní znění, schválená a nahrazená verze karty jsou jen ke čtení –
měnit jde jen návrh a karta v revizi. Stav se nemění v administraci, ale
tlačítky na stránce karty v aplikaci (k revizi, schválit, nová verze).
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    CardEvidence,
    CardRevision,
    CardSource,
    ContextScenario,
    Domain,
    ForbiddenStatement,
    GeneCard,
    GeneInteraction,
    GenePanel,
    GeneticSample,
    GeneVariant,
    Genotype,
    GenotypeText,
    PanelItem,
    Recommendation,
    ScenarioText,
)


class LockedInlineMixin:
    """Děti karty jdou měnit jen u rozpracované verze (``obj`` je karta)."""

    extra = 0

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.is_editable

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.is_editable

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.is_editable


class GenotypeTextInline(LockedInlineMixin, admin.StackedInline):
    model = GenotypeText
    fields = ("genotype", "client_text", "expert_text", "frequency", "order")


class RecommendationInline(LockedInlineMixin, admin.StackedInline):
    model = Recommendation
    fields = (("genotype", "kind", "basis"), "text", ("merge_key", "protocol", "order"))
    autocomplete_fields = ["protocol"]


class CardEvidenceInline(LockedInlineMixin, admin.StackedInline):
    model = CardEvidence
    fields = (("code", "trait", "source_labels"), "basis_text", "usage", ("article", "order"))
    autocomplete_fields = ["article"]


class CardSourceInline(LockedInlineMixin, admin.StackedInline):
    model = CardSource
    fields = (("label", "title"), "citation", ("url", "article", "order"))
    autocomplete_fields = ["article"]


class ForbiddenStatementInline(LockedInlineMixin, admin.TabularInline):
    model = ForbiddenStatement
    fields = ("text", "note")


class ContextScenarioInline(LockedInlineMixin, admin.TabularInline):
    model = ContextScenario
    fields = ("kind", "title", "statement", "question", "answer_match", "is_active", "order")
    show_change_link = True


class CardRevisionInline(admin.StackedInline):
    """Revizní záznamy se zapisují i ke schválené kartě (rozhodnutí má zůstat)."""

    model = CardRevision
    extra = 0
    fields = ("part", "original", "proposal", "reason", "source",
              ("decision", "decided_by", "decided_at"))
    readonly_fields = ("decided_by", "decided_at")


@admin.register(GeneCard)
class GeneCardAdmin(admin.ModelAdmin):
    list_display = ("__str__", "oblast", "status", "approved_by", "approved_at", "updated_at")
    list_filter = ("status", "variant__domain", "organization")
    search_fields = ("variant__gene", "variant__rsid")
    autocomplete_fields = ["variant"]
    readonly_fields = ("stav", "status", "version", "supersedes", "approved_by", "approved_at",
                       "created_by", "import_note")
    fieldsets = (
        (None, {"fields": ("stav", "organization", "variant", ("version", "status"),
                           "supersedes", "review_priorities")}),
        ("Biologie", {"fields": ("biology_expert", "biology_client", "effect", "limitations")}),
        ("Frekvence a oblasti", {"fields": ("frequency_note", "related_areas")}),
        ("Z podkladů", {"fields": ("import_note", "change_summary"), "classes": ("collapse",)}),
        ("Schválení", {"fields": ("created_by", "approved_by", "approved_at"),
                       "classes": ("collapse",)}),
    )
    inlines = [GenotypeTextInline, RecommendationInline, CardEvidenceInline, CardSourceInline,
               ForbiddenStatementInline, ContextScenarioInline, CardRevisionInline]

    @admin.display(description="oblast")
    def oblast(self, obj):
        return obj.variant.domain

    @admin.display(description="stav a akce")
    def stav(self, obj):
        if not obj.pk:
            return "Nová karta vznikne jako návrh."
        url = reverse("genetics_card", args=[obj.pk])
        hint = ("Jen ke čtení – změna je nová verze (tlačítko na stránce karty)."
                if not obj.is_editable else "Stav se mění na stránce karty v aplikaci.")
        return format_html('{} <a href="{}">Otevřít kartu v aplikaci</a>. {}',
                           obj.get_status_display(), url, hint)

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if obj is not None and not obj.is_editable:
            return base + [f.name for f in obj._meta.concrete_fields if f.name not in base]
        return base

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.is_editable

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ScenarioTextInline(admin.StackedInline):
    model = ScenarioText
    extra = 0


@admin.register(ContextScenario)
class ContextScenarioAdmin(admin.ModelAdmin):
    list_display = ("statement", "card", "kind", "question", "is_active")
    list_filter = ("kind", "is_active")
    fields = ("card", "kind", "title", "statement", "question", "answer_match", "condition",
              "is_active", "order")
    search_fields = ("statement", "card__variant__gene")
    autocomplete_fields = ["card"]
    inlines = [ScenarioTextInline]

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.card.is_editable

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.card.is_editable


@admin.register(GeneVariant)
class GeneVariantAdmin(admin.ModelAdmin):
    list_display = ("label", "domain", "genotypy", "karta", "is_active", "organization")
    list_filter = ("domain", "is_active", "organization")
    search_fields = ("gene", "rsid", "full_name")
    fieldsets = (
        (None, {"fields": ("organization", ("gene", "rsid"), "full_name", "notation",
                           ("domain", "subtitle"), ("order", "is_active"))}),
        ("Genotypy", {"fields": ("genotypes", "genotype_aliases", "strand_note",
                                 "frequency_source")}),
    )

    @admin.display(description="genotypy")
    def genotypy(self, obj):
        return ", ".join(obj.genotype_label(g) for g in obj.genotypes)

    @admin.display(description="schválená karta")
    def karta(self, obj):
        card = obj.current_card()
        return f"v{card.version}" if card else "—"


class PanelItemInline(admin.TabularInline):
    model = PanelItem
    extra = 0
    autocomplete_fields = ["variant"]


@admin.register(GenePanel)
class GenePanelAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "provider", "pocet", "is_active", "organization")
    list_filter = ("is_active", "organization")
    search_fields = ("name", "code", "provider")
    inlines = [PanelItemInline]

    @admin.display(description="variant")
    def pocet(self, obj):
        return obj.items.count()


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "garanti", "order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    filter_horizontal = ("guarantors",)

    @admin.display(description="garanti")
    def garanti(self, obj):
        return ", ".join(u.get_full_name() or u.get_username() for u in obj.guarantors.all()) or "—"


@admin.register(GeneInteraction)
class GeneInteractionAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "varianty", "source_card")
    list_filter = ("status",)
    search_fields = ("title", "assumption", "text")

    @admin.display(description="varianty")
    def varianty(self, obj):
        return ", ".join(obj.variants)


@admin.register(ForbiddenStatement)
class ForbiddenStatementAdmin(admin.ModelAdmin):
    list_display = ("text", "card", "note")
    list_filter = ("card",)
    search_fields = ("text",)
    autocomplete_fields = ["card"]


class GenotypeInline(admin.TabularInline):
    model = Genotype
    extra = 0
    fields = ("variant", "hodnota", "zapis", "quality", "note")
    readonly_fields = ("variant", "hodnota", "zapis")

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="genotyp")
    def hodnota(self, obj):
        return _decrypted(obj.value_enc)

    @admin.display(description="zápis laboratoře")
    def zapis(self, obj):
        return _decrypted(obj.raw_enc)


def _decrypted(token: str) -> str:
    from . import crypto

    if not token:
        return "—"
    try:
        return crypto.decrypt(token) or "—"
    except Exception:
        return "(nejde přečíst – jiný nebo chybějící klíč)"


@admin.register(GeneticSample)
class GeneticSampleAdmin(admin.ModelAdmin):
    """Vzorky se zadávají v aplikaci (karta sportovce → Genetika); tady jen přehled."""

    list_display = ("subject", "panel", "status", "reported_on", "verified_by", "created_at")
    list_filter = ("status", "panel")
    search_fields = ("subject__code", "external_reference")
    readonly_fields = ("subject", "panel", "consent", "entered_by", "verified_by", "verified_at",
                       "report_hash")
    inlines = [GenotypeInline]

    def has_add_permission(self, request):
        return False
