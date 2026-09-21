"""
Administrace katalogu. Tohle je hlavní pracovní plocha pro správu testů –
nový protokol nebo metrika se zakládá tady, ne v kódu.
"""

from django.contrib import admin

from .models import MetricDef, Norm, Protocol, ProtocolMetric


class ProtocolMetricInline(admin.TabularInline):
    model = ProtocolMetric
    extra = 1
    autocomplete_fields = ["metric"]


@admin.register(Protocol)
class ProtocolAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "version", "family", "device", "organization", "is_active")
    list_filter = ("family", "is_active", "organization")
    search_fields = ("code", "name", "device")
    inlines = [ProtocolMetricInline]


@admin.register(MetricDef)
class MetricDefAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "family", "unit", "direction", "mdc", "swc", "is_active")
    list_filter = ("family", "direction", "is_active", "organization")
    search_fields = ("code", "name")
    fieldsets = (
        (None, {"fields": ("organization", "code", "name", "family", "unit", "decimals",
                           "direction", "description", "is_active")}),
        ("Rozlišení změny od šumu", {
            "fields": ("typical_error", "mdc", "swc"),
            "description": "Bez MDC nelze u opakovaného měření odlišit skutečnou "
                           "změnu od chyby měření. Doplňte z literatury nebo "
                           "z vlastní reliability studie.",
        }),
        ("Validace importu", {"fields": ("plausible_min", "plausible_max")}),
        ("Mapování na standardy", {"fields": ("loinc_code",), "classes": ("collapse",)}),
    )


@admin.register(Norm)
class NormAdmin(admin.ModelAdmin):
    list_display = ("metric", "sport", "sex", "age_min", "age_max", "mean", "sd", "sample_size")
    list_filter = ("metric__family", "sport", "sex")
    search_fields = ("metric__code", "metric__name", "source_citation")
    autocomplete_fields = ["metric"]
