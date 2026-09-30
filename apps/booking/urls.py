from django.urls import path

from . import views

urlpatterns = [
    path("", views.request_list, name="booking_list"),
    path("<int:pk>/", views.request_detail, name="booking_detail"),
    path("<int:pk>/vyridit/", views.request_decide, name="booking_decide"),
    path("nabidka/", views.offer_list, name="booking_offers"),
    path("nabidka/nova/", views.offer_edit, name="booking_offer_new"),
    path("nabidka/<int:pk>/", views.offer_edit, name="booking_offer_edit"),
    path("terminy/", views.slot_list, name="booking_slots"),
]
