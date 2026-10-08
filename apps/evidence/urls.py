from django.urls import path

from . import views

urlpatterns = [
    path("", views.article_list, name="article_list"),
    path("novy/", views.article_new, name="article_new"),
    path("<int:pk>/", views.article_edit, name="article_edit"),
    path("<int:pk>/stav/", views.article_status, name="article_status"),
    path("<int:pk>/ai/", views.article_ai_state, name="article_ai_state"),
    path("<int:pk>/pdf/", views.article_pdf, name="article_pdf"),
]
