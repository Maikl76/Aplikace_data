from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="genetics_home"),
    path("vyzkum/export/", views.research_export, name="genetics_research_export"),
    path("karta/<int:pk>/", views.card, name="genetics_card"),
    path("karta/<int:pk>/akce/", views.card_action, name="genetics_card_action"),
    path("sportovec/<int:pk>/", views.subject, name="genetics_subject"),
    path("sportovec/<int:pk>/akce/", views.subject_action, name="genetics_subject_action"),
    path("sportovec/<int:pk>/dotaznik/", views.questionnaire, name="genetics_questionnaire"),
    path("sportovec/<int:pk>/zprava/", views.report_create, name="genetics_report_create"),
]
