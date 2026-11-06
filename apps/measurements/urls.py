from django.urls import path

from . import views

urlpatterns = [
    path("", views.session_list, name="session_list"),
    path("novy/", views.session_create, name="session_create"),
    path("novy/baterie/", views.session_battery, name="session_battery"),
    path("<int:pk>/", views.session_detail, name="session_detail"),
    path("<int:pk>/protokol/", views.session_add_protocol, name="session_add_protocol"),
    path("<int:pk>/prostredi/", views.session_conditions, name="session_conditions"),
    path("<int:pk>/doporuceni-minule/", views.session_followup, name="session_followup"),
    path("<int:pk>/dotaznik/", views.session_questionnaire, name="session_questionnaire"),
    path("<int:pk>/dotaznik/qr/", views.session_questionnaire_qr,
         name="session_questionnaire_qr"),
    path("<int:pk>/dotaznik/<slug:code>/", views.session_questionnaire_form,
         name="session_questionnaire_form"),
    path("provedeni/<int:pk>/", views.run_entry, name="run_entry"),
    path("provedeni/<int:pk>/u-pristroje/", views.run_device, name="run_device"),
    path("<int:pk>/u-pristroje/hotovo/", views.session_device_done, name="session_device_done"),
    path("provedeni/<int:pk>/podminky/", views.run_conditions, name="run_conditions"),
]
