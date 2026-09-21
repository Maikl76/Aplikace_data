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
