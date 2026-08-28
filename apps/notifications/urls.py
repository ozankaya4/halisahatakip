from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("okundu/<int:bildirim_id>/", views.okundu_isaretle, name="okundu"),
    path("hepsi-okundu/", views.hepsini_okundu_isaretle, name="hepsi_okundu"),
    # --- Telefona bildirim (Web Push) --------------------------------------
    path("push/ayarlar/", views.push_ayarlari, name="push_ayarlari"),
    path("push/abone/", views.push_abone_ol, name="push_abone_ol"),
    path("push/cik/", views.push_abonelikten_cik, name="push_abonelikten_cik"),
]
