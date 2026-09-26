from django.urls import path

from . import views

urlpatterns = [
    path("", views.session_list, name="session_list"),
    path("novy/", views.session_create, name="session_create"),
    path("novy/baterie/", views.session_battery, name="session_battery"),
    path("<int:pk>/", views.session_detail, name="session_detail"),
    path("<int:pk>/protokol/", views.session_add_protocol, name="session_add_protocol"),
    path("provedeni/<int:pk>/", views.run_entry, name="run_entry"),
]
