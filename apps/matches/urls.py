from django.urls import path

from . import views

app_name = "matches"

urlpatterns = [
    # Çevrimdışı için sıradaki maç özeti (bkz. static/js/cevrimdisi.js).
    path("sonraki/", views.sonraki_mac_ozeti, name="sonraki_mac_ozeti"),
    # --- Android paylaş menüsü ---------------------------------------------
    # manifest.webmanifest içindeki share_target bu adrese POST ediyor.
    path("paylasilan/", views.paylasilan_al, name="paylasilan_al"),
    path("paylasilan/sec/", views.paylasilan_sec, name="paylasilan_sec"),
    path(
        "paylasilan/dosya/<uuid:dosya_id>/",
        views.paylasilan_dosya,
        name="paylasilan_dosya",
    ),
    path("grup/<uuid:genel_id>/", views.liste, name="liste"),
    path("grup/<uuid:genel_id>/yeni/", views.olustur, name="olustur"),
    path("<int:mac_id>/", views.detay, name="detay"),
    path("<int:mac_id>/duzenle/", views.duzenle, name="duzenle"),
    path("<int:mac_id>/iptal/", views.iptal_durumu, name="iptal_durumu"),
    path("<int:mac_id>/sil/", views.sil, name="sil"),
    path("<int:mac_id>/yoklama/", views.yoklama_oyu, name="yoklama_oyu"),
    path("<int:mac_id>/yoklama-durumu/", views.yoklama_durumu, name="yoklama_durumu"),
    path("<int:mac_id>/kadro/", views.kadro_duzenle, name="kadro_duzenle"),
    path("<int:mac_id>/dizilim/", views.dizilim, name="dizilim"),
    path("<int:mac_id>/dizilim/duzenle/", views.dizilim_duzenle, name="dizilim_duzenle"),
    path("<int:mac_id>/dizilim/gorsel.png", views.dizilim_gorseli, name="dizilim_gorseli"),
    path("<int:mac_id>/fotograf/", views.fotograf_yukle, name="fotograf_yukle"),
    path("fotograf/<int:foto_id>/sil/", views.fotograf_sil, name="fotograf_sil"),
]
