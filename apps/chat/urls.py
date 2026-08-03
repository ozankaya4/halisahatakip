from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("anahtar/", views.anahtar_kurulumu, name="anahtar_kurulumu"),
    path("<uuid:genel_id>/", views.sohbet, name="sohbet"),
    # --- JSON uçları -------------------------------------------------------
    path("api/anahtar/", views.api_kendi_anahtarim, name="api_kendi_anahtarim"),
    path("api/anahtar/sifirla/", views.api_anahtar_sifirla, name="api_anahtar_sifirla"),
    path("api/<uuid:genel_id>/durum/", views.api_durum, name="api_durum"),
    path("api/<uuid:genel_id>/anahtar/", views.api_anahtar_yayinla, name="api_anahtar_yayinla"),
    path("api/<uuid:genel_id>/paket/", views.api_paket_ekle, name="api_paket_ekle"),
    path("api/<uuid:genel_id>/mesajlar/", views.api_mesajlar, name="api_mesajlar"),
]
