from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuditLog, Organization, User, default_organization

# Skupina, do které role uživatele patří, je v roles.py – stejné párování používá
# administrace i stránka Kolegové. ROLE_GROUPS odtud importují jiné části.
from .roles import ROLE_GROUPS, sync_groups  # noqa: F401

admin.site.site_header = "Funkční testování — administrace"
admin.site.site_title = "Funkční testování"
admin.site.index_title = "Správa aplikace"


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "is_active")
    search_fields = ("name", "short_name")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "get_full_name", "organization", "role",
                    "is_active", "is_staff")
    list_filter = ("organization", "role", "is_active", "is_staff")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Pracoviště a role", {"fields": ("organization", "role")}),
    )
    # Výchozí formulář pro nového uživatele umí jen jméno a heslo. Bez
    # tohohle by se pracoviště a role musely doplňovat až druhým krokem
    # a snadno by se zapomnělo.
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "password1", "password2"),
        }),
        ("Pracoviště a role", {
            "fields": ("first_name", "last_name", "email",
                       "organization", "role", "is_staff"),
            "description": "Do administrace se dostane jen uživatel "
                           "s příznakem „Stav týmu“. Trenéři a sportovci "
                           "ho mít nemají — ti pracují v samotné aplikaci, "
                           "která hlídá, na čí data vidí.",
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        """Pracoviště je povinné: účet bez něj v aplikaci nevidí nic."""
        form = super().get_form(request, obj, **kwargs)
        field = form.base_fields.get("organization")
        if field is not None and Organization.objects.exists():
            field.required = True
            field.initial = field.initial or default_organization()
            field.help_text = "Bez pracoviště by účet v aplikaci neviděl žádná data."
        return form

    def save_model(self, request, obj, form, change):
        """Role není jen popisek – po uložení se srovnají skupiny."""
        super().save_model(request, obj, form, change)
        sync_groups(obj)


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
