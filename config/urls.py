from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core.forms import LoginForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ucet/prihlaseni/", auth_views.LoginView.as_view(
        template_name="registration/login.html", authentication_form=LoginForm), name="login"),
    path("ucet/odhlaseni/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.core.urls")),
    path("sportovci/", include("apps.subjects.urls")),
    path("mereni/", include("apps.measurements.urls")),
    path("zpravy/", include("apps.reports.urls")),
    path("import/", include("apps.ingest.urls")),
]
