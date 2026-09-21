from django.contrib import admin

from .models import ExternalExam


@admin.register(ExternalExam)
class ExternalExamAdmin(admin.ModelAdmin):
    list_display = ("subject", "exam_type", "date", "provider", "load_restriction",
                    "restriction_valid_until")
    list_filter = ("exam_type", "load_restriction", "provider")
    search_fields = ("subject__code", "external_reference")
