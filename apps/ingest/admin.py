from django.contrib import admin

from .models import ImportBatch, StagedMeasurement


class StagedMeasurementInline(admin.TabularInline):
    model = StagedMeasurement
    extra = 0


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("raw_file", "adapter", "protocol", "status", "uploaded_by", "created_at")
    list_filter = ("status", "adapter")
    inlines = [StagedMeasurementInline]
