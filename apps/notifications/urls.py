from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("okundu/<int:bildirim_id>/", views.okundu_isaretle, name="okundu"),
    path("hepsi-okundu/", views.hepsini_okundu_isaretle, name="hepsi_okundu"),
]
