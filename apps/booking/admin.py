from django.contrib import admin

from .models import BookingRequest, Offer, Slot


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "price", "is_active", "organization")
    list_filter = ("kind", "is_active")
    filter_horizontal = ("protocols",)


@admin.register(Slot)
class SlotAdmin(admin.ModelAdmin):
    list_display = ("start", "location", "capacity", "is_active")
    list_filter = ("location", "is_active")
    date_hierarchy = "start"


@admin.register(BookingRequest)
class BookingRequestAdmin(admin.ModelAdmin):
    """Jen přehled – osobní údaje jsou šifrované a vyřizují se v aplikaci."""

    list_display = ("number", "kind", "status", "slot", "price_total", "created_at")
    list_filter = ("status", "kind")
    fields = ("kind", "status", "slot", "price_total", "team_name", "sport_name", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False
