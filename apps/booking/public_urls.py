"""Veřejné adresy objednávky – jediné (spolu s /d/ pro RPE), které mají být vidět z internetu."""

from django.urls import path

from . import public

urlpatterns = [
    path("", public.booking_form, name="booking_form"),
    path("potvrdit/<str:token>/", public.booking_verify, name="booking_verify"),
    path("stav/<str:token>/", public.booking_status, name="booking_status"),
]
