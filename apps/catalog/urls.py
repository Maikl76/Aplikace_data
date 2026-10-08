from django.urls import path

from apps.evidence import views as article_views

from . import battery_views as views
from . import protocol_views

urlpatterns = [
    path("", views.sport_list, name="sport_list"),
    path("testy/", protocol_views.test_list, name="test_list"),
    path("testy/novy/", protocol_views.test_new, name="test_new"),
    path("testy/<int:pk>/", protocol_views.test_edit, name="test_edit"),
    path("clanky/", article_views.article_list, name="article_list"),
    path("clanky/novy/", article_views.article_new, name="article_new"),
    path("clanky/<int:pk>/", article_views.article_edit, name="article_edit"),
    path("clanky/<int:pk>/stav/", article_views.article_status, name="article_status"),
    path("clanky/<int:pk>/ai/", article_views.article_ai_state, name="article_ai_state"),
    path("clanky/<int:pk>/pdf/", article_views.article_pdf, name="article_pdf"),
    path("<int:sport_pk>/baterie/", views.battery_add, name="battery_add"),
    path("baterie/<int:pk>/smazat/", views.battery_delete, name="battery_delete"),
    path("baterie/<int:pk>/pridat/", views.battery_item_add, name="battery_item_add"),
    path("polozka/<int:pk>/odebrat/", views.battery_item_remove, name="battery_item_remove"),
    path("polozka/<int:pk>/<str:direction>/", views.battery_item_move, name="battery_item_move"),
]
