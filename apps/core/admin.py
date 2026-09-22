from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group

from .models import AuditLog, Organization, Role, User

admin.site.site_header = "Funkční testování — administrace"
admin.site.site_title = "Funkční testování"
admin.site.index_title = "Správa aplikace"

# Skupina, do které role uživatele patří. Role sama o sobě nic nepovoluje –
# oprávnění nese skupina, a tohle je jediné místo, kde se to páruje.
ROLE_GROUPS = {
    Role.ADMIN: "Správce",
    Role.LAB: "Diagnostik",
    Role.RESEARCHER: "Výzkumník",
}


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

    def save_model(self, request, obj, form, change):
        """Role není jen popisek – po uložení se srovnají skupiny."""
        super().save_model(request, obj, form, change)
        self._sync_groups(obj)

    def _sync_groups(self, user):
        wanted = ROLE_GROUPS.get(user.role)
        managed = Group.objects.filter(name__in=ROLE_GROUPS.values())
        user.groups.remove(*managed.exclude(name=wanted))
        if wanted:
            group = Group.objects.filter(name=wanted).first()
            if group:
                user.groups.add(group)


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
