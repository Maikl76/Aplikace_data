from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.core.forms import LoginForm
from apps.measurements import views as measurement_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ucet/prihlaseni/", auth_views.LoginView.as_view(
        template_name="registration/login.html", authentication_form=LoginForm), name="login"),
    path("ucet/odhlaseni/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.core.urls")),
    path("sportovci/", include("apps.subjects.urls")),
    path("sporty/", include("apps.catalog.urls")),
    path("testovani/", measurement_views.today, name="today"),
    path("tym/", measurement_views.team, name="team"),
    # Dotazník pro sportovce na jeho telefonu – bez přihlášení, s podepsaným odkazem.
    path("d/<str:token>/", measurement_views.questionnaire_fill, name="questionnaire_fill"),
    path("mereni/", include("apps.measurements.urls")),
    path("zpravy/", include("apps.reports.urls")),
    path("import/", include("apps.ingest.urls")),
]
