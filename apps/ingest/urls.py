from django.urls import path

from . import views

urlpatterns = [
    path("", views.import_list, name="import_list"),
    path("nahrat/", views.import_upload, name="import_upload"),
    path("<int:pk>/", views.import_detail, name="import_detail"),
    path("<int:pk>/ulozit/", views.import_commit, name="import_commit"),
    path("<int:pk>/zrusit/", views.import_cancel, name="import_cancel"),
]
