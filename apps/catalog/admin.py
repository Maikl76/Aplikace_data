"""
Administrace katalogu. Tohle je hlavní pracovní plocha pro správu testů –
nový protokol nebo metrika se zakládá tady, ne v kódu.
"""

from django.contrib import admin
from django.shortcuts import redirect

from .models import (
    BatteryItem,
    DeviceFormat,
    ImportColumn,
    ImportProfile,
    MetricDef,
    Norm,
    Protocol,
    ProtocolMetric,
    Question,
    Questionnaire,
    TestBattery,
)


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

    def add_view(self, request, form_url="", extra_context=None):
        """Nový test se pohodlněji zakládá v aplikaci (Sporty a testy → Testy)."""
        return redirect("test_new")


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
        ("Pokusy a diagnostika", {"fields": ("trial_rule", "trial_cv_limit", "ods_role")}),
        ("Validace importu", {"fields": ("plausible_min", "plausible_max")}),
        ("Mapování na standardy", {"fields": ("loinc_code",), "classes": ("collapse",)}),
    )


@admin.register(Norm)
class NormAdmin(admin.ModelAdmin):
    list_display = ("metric", "sport", "sex", "age_min", "age_max", "mean", "sd", "sample_size")
    list_filter = ("metric__family", "sport", "sex")
    search_fields = ("metric__code", "metric__name", "source_citation")
    autocomplete_fields = ["metric"]


class ImportColumnInline(admin.TabularInline):
    model = ImportColumn
    extra = 1
    autocomplete_fields = ["metric"]


@admin.register(ImportProfile)
class ImportProfileAdmin(admin.ModelAdmin):
    """
    Které sloupce exportu z přístroje se importují. Nová metrika z VALD =
    nový řádek tady (a metrika v katalogu), nic se neprogramuje.
    """

    list_display = ("test_type", "pristroj", "protocol", "pocet_sloupcu", "is_active")
    list_filter = ("device", "is_active")
    search_fields = ("test_type",)
    inlines = [ImportColumnInline]

    @admin.display(description="přístroj", ordering="device")
    def pristroj(self, obj):
        return obj.device_label

    @admin.display(description="sloupců")
    def pocet_sloupcu(self, obj):
        return obj.columns.count()


@admin.register(DeviceFormat)
class DeviceFormatAdmin(admin.ModelAdmin):
    """Přístroje z průvodce se nastavují v aplikaci (Import → Přístroje), tady jen odkaz."""

    def changelist_view(self, request, extra_context=None):
        return redirect("import_list")

    def add_view(self, request, form_url="", extra_context=None):
        return redirect("device_new")

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return redirect("device_edit", pk=object_id)


class BatteryItemInline(admin.TabularInline):
    model = BatteryItem
    extra = 1
    autocomplete_fields = ["protocol"]


@admin.register(TestBattery)
class TestBatteryAdmin(admin.ModelAdmin):
    """Pohodlněji se baterie upravují v aplikaci (Sporty a testy); tady pro úplnost."""

    list_display = ("sport", "category", "name")
    list_filter = ("sport",)
    inlines = [BatteryItemInline]


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 0


@admin.register(Questionnaire)
class QuestionnaireAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization", "is_active")
    search_fields = ("code", "name")
    inlines = [QuestionInline]
