from django.urls import path

from . import setup_views, views

urlpatterns = [
    path("", views.home, name="genetics_home"),
    path("vyzkum/export/", views.research_export, name="genetics_research_export"),
    path("navod/", setup_views.guide, name="genetics_guide"),
    path("nastaveni/garanti/", setup_views.setup_guarantors, name="genetics_setup_guarantors"),
    path("nastaveni/karty/", setup_views.setup_cards, name="genetics_setup_cards"),
    path("nastaveni/panel/", setup_views.setup_panel, name="genetics_setup_panel"),
    path("karta/<int:pk>/upravit/", setup_views.card_edit, name="genetics_card_edit"),
    path("karta/<int:pk>/", views.card, name="genetics_card"),
    path("karta/<int:pk>/akce/", views.card_action, name="genetics_card_action"),
    path("sportovec/<int:pk>/", views.subject, name="genetics_subject"),
    path("sportovec/<int:pk>/akce/", views.subject_action, name="genetics_subject_action"),
    path("sportovec/<int:pk>/dotaznik/", views.questionnaire, name="genetics_questionnaire"),
    path("sportovec/<int:pk>/zprava/", views.report_create, name="genetics_report_create"),
]
