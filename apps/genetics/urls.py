from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="genetics_home"),
    path("karta/<int:pk>/", views.card, name="genetics_card"),
    path("karta/<int:pk>/akce/", views.card_action, name="genetics_card_action"),
    path("sportovec/<int:pk>/", views.subject, name="genetics_subject"),
    path("sportovec/<int:pk>/akce/", views.subject_action, name="genetics_subject_action"),
]
