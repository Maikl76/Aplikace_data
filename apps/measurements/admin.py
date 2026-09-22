from django.contrib import admin

from .models import Measurement, ProtocolRun, RawFile, TestSession, Trial


class ProtocolRunInline(admin.TabularInline):
    model = ProtocolRun
    extra = 0


@admin.register(TestSession)
class TestSessionAdmin(admin.ModelAdmin):
    list_display = ("subject", "date", "location", "operator", "season_phase")
    list_filter = ("date", "season_phase", "organization")
    search_fields = ("subject__code",)
    date_hierarchy = "date"
    inlines = [ProtocolRunInline]


class MeasurementInline(admin.TabularInline):
    model = Measurement
    extra = 0
    autocomplete_fields = ["metric"]


@admin.register(Trial)
class TrialAdmin(admin.ModelAdmin):
    list_display = ("protocol_run", "number", "is_valid")
    list_filter = ("is_valid",)
    inlines = [MeasurementInline]


@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    """
    Samostatný seznam hodnot – na opravu jedné špatně zadané hodnoty.
    Běžně se hodnoty zadávají v mřížce u přístroje, ne tady.
    """

    list_display = ("sportovec", "datum", "metric", "side", "mode", "speed",
                    "segment", "value", "quality")
    list_filter = ("quality", "metric__family", "metric", "side", "mode")
    search_fields = ("trial__protocol_run__session__subject__code", "metric__code")
    autocomplete_fields = ["metric"]
    list_select_related = True

    @admin.display(description="sportovec", ordering="trial__protocol_run__session__subject__code")
    def sportovec(self, obj):
        return obj.trial.protocol_run.session.subject.code

    @admin.display(description="datum", ordering="trial__protocol_run__session__date")
    def datum(self, obj):
        return obj.trial.protocol_run.session.date

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "metric", "trial__protocol_run__session__subject")


@admin.register(RawFile)
class RawFileAdmin(admin.ModelAdmin):
    list_display = ("original_name", "device", "format", "size_bytes", "created_at")
    search_fields = ("original_name", "content_hash")
    readonly_fields = ("content_hash", "size_bytes")
