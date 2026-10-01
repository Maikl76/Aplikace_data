from django.urls import path

from . import device_views, views

urlpatterns = [
    path("", views.import_list, name="import_list"),
    path("nahrat/", views.import_upload, name="import_upload"),
    path("<int:pk>/", views.import_detail, name="import_detail"),
    path("<int:pk>/ulozit/", views.import_commit, name="import_commit"),
    path("<int:pk>/znovu/", views.import_restage, name="import_restage"),
    path("<int:pk>/zrusit/", views.import_cancel, name="import_cancel"),
    path("pristroje/novy/", device_views.device_new, name="device_new"),
    path("pristroje/<int:pk>/", device_views.device_edit, name="device_edit"),
    path("pristroje/<int:pk>/ukazka/", device_views.device_sample, name="device_sample"),
    path("pristroje/<int:pk>/smazat/", device_views.device_delete, name="device_delete"),
]
