from django.urls import path

from . import views

urlpatterns = [
    path("", views.subject_list, name="subject_list"),
    path("hledat/", views.subject_search, name="subject_search"),
    path("<int:pk>/", views.subject_detail, name="subject_detail"),
    path("<int:pk>/qr/", views.subject_qr, name="subject_qr"),
    path("<int:pk>/dnes/", views.subject_today, name="subject_today"),
    path("qr-karty/", views.team_qr, name="team_qr"),
]
