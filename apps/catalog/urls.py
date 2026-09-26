from django.urls import path

from . import battery_views as views

urlpatterns = [
    path("", views.sport_list, name="sport_list"),
    path("<int:sport_pk>/baterie/", views.battery_add, name="battery_add"),
    path("baterie/<int:pk>/smazat/", views.battery_delete, name="battery_delete"),
    path("baterie/<int:pk>/pridat/", views.battery_item_add, name="battery_item_add"),
    path("polozka/<int:pk>/odebrat/", views.battery_item_remove, name="battery_item_remove"),
    path("polozka/<int:pk>/<str:direction>/", views.battery_item_move, name="battery_item_move"),
]
