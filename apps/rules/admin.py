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
            "description": 'Např. {"metric": "ir_er_ratio", "op": "&lt;", "value": 1.0, '
                           '"speed": 210}. Kontraindikace pravidlo potlačí – typicky '
                           'platné omezení zátěže.',
        }),
        ("Texty", {"fields": ("finding_template", "recommendation_template")}),
    )


@admin.register(Finding)
class FindingAdmin(admin.ModelAdmin):
    list_display = ("session", "rule", "severity", "suppressed")
    list_filter = ("severity", "suppressed", "rule")
    readonly_fields = ("values", "text", "rule_version")
