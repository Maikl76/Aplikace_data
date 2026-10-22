from django.urls import path

from . import views

urlpatterns = [
    path("", views.coach_home, name="coach_home"),
    path("<int:pk>/", views.coach_subject, name="coach_subject"),
    path("<int:pk>/zprava/<int:report_pk>/", views.coach_report, name="coach_report"),
    path("<int:pk>/zprava/<int:report_pk>/pdf/", views.coach_report_pdf, name="coach_report_pdf"),
]
