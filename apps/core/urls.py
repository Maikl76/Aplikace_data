from django.urls import path
from django.views.generic import RedirectView

from apps.analytics import reference_views
from apps.catalog import norm_views, questionnaire_views, settings_views, transfer_views
from apps.rules import setup_views as rule_views

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("o-aplikaci/", views.about, name="about"),
    path("kolegove/", views.colleagues, name="colleagues"),
    path("kolegove/<int:pk>/pristup/", views.colleague_access, name="colleague_access"),
    path("nastaveni/", views.workplace, name="workplace"),
    path("stav/", RedirectView.as_view(url="/nastaveni/", permanent=True)),  # starý odkaz
    path("nastaveni/pracoviste/", views.organization_settings, name="workplace_org"),
    path("nastaveni/provoz/", views.operations, name="operations"),
    path("nastaveni/prenos/", transfer_views.transfer_settings, name="transfer_settings"),
    path("nastaveni/prenos/<int:pk>/", transfer_views.transfer_preview, name="transfer_preview"),
    path("nastaveni/mdc/", settings_views.mdc_settings, name="mdc_settings"),
    path("nastaveni/popisy/", settings_views.client_texts, name="client_texts"),
    path("nastaveni/import/", settings_views.import_profiles, name="import_profiles"),
    path("nastaveni/normy/", norm_views.norm_list, name="norms_settings"),
    path("nastaveni/reference/", reference_views.reference_settings, name="reference_settings"),
    path("nastaveni/normy/nova/", norm_views.norm_edit, name="norm_new"),
    path("nastaveni/normy/<int:pk>/", norm_views.norm_edit, name="norm_edit"),
    path("nastaveni/normy/<int:pk>/smazat/", norm_views.norm_delete, name="norm_delete"),
    path("nastaveni/pravidla/", rule_views.rule_list, name="rules_settings"),
    path("nastaveni/pravidla/nove/", rule_views.rule_edit, name="rule_new"),
    path("nastaveni/pravidla/zkouska/", rule_views.rule_test, name="rules_test"),
    path("nastaveni/pravidla/<int:pk>/", rule_views.rule_edit, name="rule_edit"),
    path("nastaveni/pravidla/<int:pk>/smazat/", rule_views.rule_delete, name="rule_delete"),
    path("nastaveni/pravidla/<int:pk>/zkouska/", rule_views.rule_test, name="rule_test"),
    path("nastaveni/dotazniky/", questionnaire_views.questionnaire_list,
         name="questionnaires_settings"),
    path("nastaveni/dotazniky/novy/", questionnaire_views.questionnaire_edit,
         name="questionnaire_new"),
    path("nastaveni/dotazniky/<int:pk>/", questionnaire_views.questionnaire_edit,
         name="questionnaire_edit"),
    path("nastaveni/dotazniky/<int:pk>/smazat/", questionnaire_views.questionnaire_delete,
         name="questionnaire_delete"),
    path("nastaveni/dotazniky/<int:pk>/otazka/nova/", questionnaire_views.question_edit,
         name="question_new"),
    path("nastaveni/dotazniky/<int:pk>/otazka/<int:qpk>/", questionnaire_views.question_edit,
         name="question_edit"),
    path("nastaveni/dotazniky/<int:pk>/otazka/<int:qpk>/smazat/",
         questionnaire_views.question_delete, name="question_delete"),
    path("pripominky/", views.remarks, name="remarks"),
    path("pripominky/nova/", views.remark_new, name="remark_new"),
    path("zdravi/", views.health, name="health"),
]
