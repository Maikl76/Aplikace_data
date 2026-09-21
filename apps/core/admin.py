from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuditLog, Organization, User


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "is_active")
    search_fields = ("name", "short_name")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "organization", "role", "is_active")
    list_filter = ("organization", "role", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Pracoviště a role", {"fields": ("organization", "role")}),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "object_type", "subject_code")
    list_filter = ("action", "object_type")
    search_fields = ("subject_code", "object_id")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
