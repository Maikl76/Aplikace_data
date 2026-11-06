from django.urls import path

from . import views

urlpatterns = [
    path("nove/", views.exam_edit, name="exam_new"),
    path("<int:epk>/", views.exam_edit, name="exam_edit"),
    path("<int:epk>/smazat/", views.exam_delete, name="exam_delete"),
]
