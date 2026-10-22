from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="portal_home"),
    path("souhlasy/", views.consents_home, name="portal_consents_home"),
    path("ucet/", views.account, name="portal_account"),
    path("<int:pk>/", views.subject, name="portal_subject"),
    path("<int:pk>/souhlasy/", views.consents, name="portal_consents"),
    path("<int:pk>/dotaznik/", views.questionnaire, name="portal_questionnaire"),
    path("<int:pk>/zprava/<int:report_pk>/", views.report, name="portal_report"),
    path("<int:pk>/zprava/<int:report_pk>/pdf/", views.report_pdf, name="portal_report_pdf"),
]
