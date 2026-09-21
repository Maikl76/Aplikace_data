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


@admin.register(RawFile)
class RawFileAdmin(admin.ModelAdmin):
    list_display = ("original_name", "device", "format", "size_bytes", "created_at")
    search_fields = ("original_name", "content_hash")
    readonly_fields = ("content_hash", "size_bytes")
