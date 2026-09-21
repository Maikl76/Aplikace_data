from django.contrib import admin

from .models import Consent, Sport, Subject, SubjectIdentity, Team


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization")


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "sport", "organization")
    list_filter = ("sport",)


class ConsentInline(admin.TabularInline):
    model = Consent
    extra = 0


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "sport", "team", "sex", "birth_year", "level", "is_active")
    list_filter = ("sport", "team", "sex", "level", "is_active")
    search_fields = ("code",)
    inlines = [ConsentInline]


@admin.register(SubjectIdentity)
class SubjectIdentityAdmin(admin.ModelAdmin):
    """Identita je citlivá – v administraci jen pro superuživatele."""

    list_display = ("subject",)
    search_fields = ("subject__code",)

    def has_module_permission(self, request):
        return request.user.is_superuser
