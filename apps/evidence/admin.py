from django.contrib import admin

from .models import Article


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title_short", "year", "journal", "evidence_level", "status")
    list_filter = ("status", "evidence_level", "year", "population_sex")
    search_fields = ("title", "authors", "doi", "pmid")
    actions = ["schvalit", "zamitnout"]
    fieldsets = (
        (None, {"fields": ("status", "title", "authors", "journal", "year", "doi", "pmid",
                           "url", "abstract")}),
        ("Kurátorské hodnocení", {"fields": ("evidence_level", "curator_note", "tags")}),
        ("Populace", {
            "fields": ("population_sport", "population_sex", "population_age_min",
                       "population_age_max", "population_level", "sample_size"),
            "description": "Studie na mužích fotbalistech neospravedlňuje doporučení "
                           "pro sedmnáctiletou tenistku. Zpráva na neshodu populace "
                           "upozorní, pokud je tu vyplněná.",
        }),
    )

    @admin.display(description="název")
    def title_short(self, obj):
        return obj.title[:80]

    @admin.action(description="Zařadit do knihovny")
    def schvalit(self, request, queryset):
        queryset.update(status=Article.Status.APPROVED)

    @admin.action(description="Zamítnout")
    def zamitnout(self, request, queryset):
        queryset.update(status=Article.Status.REJECTED)
