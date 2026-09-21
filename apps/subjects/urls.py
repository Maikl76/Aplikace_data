from django.urls import path

from . import views

urlpatterns = [
    path("", views.subject_list, name="subject_list"),
    path("<int:pk>/", views.subject_detail, name="subject_detail"),
]
