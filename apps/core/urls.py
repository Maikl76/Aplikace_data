from django.urls import path
from django.views.generic import RedirectView

from apps.catalog import settings_views

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("o-aplikaci/", views.about, name="about"),
    path("kolegove/", views.colleagues, name="colleagues"),
    path("nastaveni/", views.workplace, name="workplace"),
    path("stav/", RedirectView.as_view(url="/nastaveni/", permanent=True)),  # starý odkaz
    path("nastaveni/pracoviste/", views.organization_settings, name="workplace_org"),
    path("nastaveni/mdc/", settings_views.mdc_settings, name="mdc_settings"),
    path("nastaveni/import/", settings_views.import_profiles, name="import_profiles"),
    path("pripominky/", views.remarks, name="remarks"),
    path("pripominky/nova/", views.remark_new, name="remark_new"),
    path("zdravi/", views.health, name="health"),
]
