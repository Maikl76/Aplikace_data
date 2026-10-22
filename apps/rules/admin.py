from django.contrib import admin

from .models import Finding, Rule, RuleArticle


class RuleArticleInline(admin.TabularInline):
    model = RuleArticle
    extra = 1
    autocomplete_fields = ["article"]


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "version", "severity", "applies_to_sport", "is_active")
    list_filter = ("severity", "is_active", "applies_to_sport")
    search_fields = ("code", "name")
    inlines = [RuleArticleInline]
    fieldsets = (
        (None, {"fields": ("organization", "code", "name", "version", "applies_to_sport",
                           "severity", "is_active")}),
        ("Podmínka", {
            "fields": ("condition", "contraindication"),
            "description": (
                'Podmínka, např. {"metric": "ir_er_ratio", "op": "&lt;", "value": 1.0, '
                '"where": {"speed": 210}} – strana, režim, rychlost a segment patří do '
                '"where". Druhy: metric (hodnota), asymmetry (rozdíl stran v %, kód nebo '
                '"*"), change (změna proti minule, jen nad MDC), z (z-skóre proti normě); '
                'skládání {"all": [...]} / {"any": [...]}. Kontraindikace '
                '{"load_restriction": true} pravidlo potlačí, když má sportovec platné '
                'omezení zátěže od lékaře. Tvar se při uložení kontroluje.'),
        }),
        ("Texty", {"fields": ("finding_template", "recommendation_template")}),
    )


@admin.register(Finding)
class FindingAdmin(admin.ModelAdmin):
    list_display = ("session", "rule", "severity", "suppressed")
    list_filter = ("severity", "suppressed", "rule")
    readonly_fields = ("values", "text", "rule_version")
