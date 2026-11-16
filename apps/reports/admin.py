from django.contrib import admin

from .models import Report, ReportDelivery


class ReportDeliveryInline(admin.TabularInline):
    model = ReportDelivery
    extra = 0
    readonly_fields = ("delivered_at", "delivered_by")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("report_number", "subject", "version", "status", "released_at")
    list_filter = ("status", "organization")
    search_fields = ("report_number", "subject__code")
    readonly_fields = ("input_fingerprint", "released_at", "released_by")
    inlines = [ReportDeliveryInline]

    def get_readonly_fields(self, request, obj=None):
        # Vydaná zpráva se needituje – oprava se řeší novou verzí.
        if obj and obj.status != Report.Status.DRAFT:
            return [f.name for f in Report._meta.fields]
        return super().get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Smazat jde jen koncept. Vydaná, nahrazená ani stažená zpráva se
        # nemaže ani tady – zůstává v archivu (platí i pro hromadné mazání).
        if obj is not None and not obj.can_delete:
            return False
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        self._delete_draft(request, obj)

    def delete_queryset(self, request, queryset):
        for report in queryset:
            self._delete_draft(request, report)

    def _delete_draft(self, request, report):
        """Stejná cesta jako v aplikaci: číslo se nepřidělí znovu, den si smazání pamatuje."""
        from django.contrib import messages

        from . import services

        try:
            services.delete_draft(report, user=request.user)
        except services.ReportError as exc:
            self.message_user(request, f"{report.report_number}: {exc}", level=messages.ERROR)
