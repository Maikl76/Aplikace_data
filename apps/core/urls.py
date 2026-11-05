from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("o-aplikaci/", views.about, name="about"),
    path("kolegove/", views.colleagues, name="colleagues"),
    path("zdravi/", views.health, name="health"),
]
