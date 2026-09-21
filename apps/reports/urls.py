from django.urls import path

from . import views

urlpatterns = [
    path("", views.report_list, name="report_list"),
    path("z-mereni/<int:session_pk>/", views.report_create, name="report_create"),
    path("<int:pk>/", views.report_detail, name="report_detail"),
    path("<int:pk>/nahled/", views.report_preview, name="report_preview"),
    path("<int:pk>/vydat/", views.report_release, name="report_release"),
    path("<int:pk>/predat/", views.report_deliver, name="report_deliver"),
    path("<int:pk>/nova-verze/", views.report_supersede, name="report_supersede"),
    path("<int:pk>/pdf/", views.report_pdf, name="report_pdf"),
]
