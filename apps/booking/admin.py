"""
Objednávky se vyřizují v aplikaci (menu Objednávky), ne tady: schválení
zakládá sportovce a testovací dny a údaje jsou šifrované. Administrace
proto na stránky aplikace jen přesměruje – ať se nikdo nehledá ve dvou
místech.
"""

from django.contrib import admin
from django.shortcuts import redirect

from .models import BookingRequest, Offer, Slot


class _InApp(admin.ModelAdmin):
    list_url = ""
    detail_url = ""

    def changelist_view(self, request, extra_context=None):
        return redirect(self.list_url)

    def add_view(self, request, form_url="", extra_context=None):
        return redirect(self.detail_url.replace("_edit", "_new") if self.detail_url
                        else self.list_url)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if self.detail_url:
            return redirect(self.detail_url, pk=object_id)
        return redirect(self.list_url)


@admin.register(BookingRequest)
class BookingRequestAdmin(_InApp):
    list_url = "booking_list"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return redirect("booking_detail", pk=object_id)

    def has_add_permission(self, request):
        return False


@admin.register(Offer)
class OfferAdmin(_InApp):
    list_url = "booking_offers"
    detail_url = "booking_offer_edit"


@admin.register(Slot)
class SlotAdmin(_InApp):
    list_url = "booking_slots"
