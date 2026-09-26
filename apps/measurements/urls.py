from django.urls import path

from . import views

urlpatterns = [
    path("", views.session_list, name="session_list"),
    path("novy/", views.session_create, name="session_create"),
    path("novy/baterie/", views.session_battery, name="session_battery"),
    path("<int:pk>/", views.session_detail, name="session_detail"),
    path("<int:pk>/protokol/", views.session_add_protocol, name="session_add_protocol"),
    path("<int:pk>/prostredi/", views.session_conditions, name="session_conditions"),
    path("<int:pk>/dotaznik/", views.session_questionnaire, name="session_questionnaire"),
    path("<int:pk>/dotaznik/qr/", views.session_questionnaire_qr,
         name="session_questionnaire_qr"),
    path("provedeni/<int:pk>/", views.run_entry, name="run_entry"),
]
