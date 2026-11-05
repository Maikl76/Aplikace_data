from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("o-aplikaci/", views.about, name="about"),
    path("kolegove/", views.colleagues, name="colleagues"),
    path("stav/", views.workplace, name="workplace"),
    path("pripominky/", views.remarks, name="remarks"),
    path("pripominky/nova/", views.remark_new, name="remark_new"),
    path("zdravi/", views.health, name="health"),
]
