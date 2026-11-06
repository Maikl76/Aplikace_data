from django.urls import path
from django.views.generic import RedirectView

from apps.catalog import norm_views, settings_views

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
    path("nastaveni/normy/", norm_views.norm_list, name="norms_settings"),
    path("nastaveni/normy/nova/", norm_views.norm_edit, name="norm_new"),
    path("nastaveni/normy/<int:pk>/", norm_views.norm_edit, name="norm_edit"),
    path("nastaveni/normy/<int:pk>/smazat/", norm_views.norm_delete, name="norm_delete"),
    path("pripominky/", views.remarks, name="remarks"),
    path("pripominky/nova/", views.remark_new, name="remark_new"),
    path("zdravi/", views.health, name="health"),
]
