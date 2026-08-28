from django.urls import path

from . import views

app_name = "groups"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("yeni/", views.olustur, name="olustur"),
    # Davet bağlantısının açılış sayfası.
    #
    # Jeton URL YOLUNDA DEĞİL, adresin # işaretinden sonraki parçasında
    # taşınıyor. Tarayıcılar bu parçayı sunucuya hiç göndermez: ne istek
    # satırına, ne Referer başlığına, ne de erişim günlüklerine girer.
    #
    # Eskiden yol "katil/<jeton>/" idi. Veritabanı jetonun yalnızca SHA-256
    # özetini saklıyor ("veritabanı sızsa bile çalışan davet üretilemesin"
    # diye) ama jetonun kendisi nginx ve gunicorn erişim günlüklerine düz
    # metin olarak yazılıyordu; özet saklamanın amacı o kapıdan boşa
    # çıkıyordu. Jeton artık sunucuya yalnızca POST gövdesinde ulaşıyor.
    path("katil/", views.davet_ile_katil, name="davet_ile_katil"),
    path("<uuid:genel_id>/", views.detay, name="detay"),
    path("<uuid:genel_id>/duzenle/", views.duzenle, name="duzenle"),
    path("<uuid:genel_id>/uyeler/", views.uyeler, name="uyeler"),
    path(
        "<uuid:genel_id>/uye/<int:kullanici_id>/istatistik/",
        views.uye_istatistik,
        name="uye_istatistik",
    ),
    path("<uuid:genel_id>/davetler/", views.davetler, name="davetler"),
    path("<uuid:genel_id>/davet/<int:davet_id>/iptal/", views.davet_iptal, name="davet_iptal"),
    path("<uuid:genel_id>/istek/<int:uyelik_id>/karar/", views.istek_karari, name="istek_karari"),
    path("<uuid:genel_id>/uye/<int:uyelik_id>/rol/", views.rol_degistir, name="rol_degistir"),
    path("<uuid:genel_id>/uye/<int:uyelik_id>/cikar/", views.uye_cikar, name="uye_cikar"),
    path("<uuid:genel_id>/ayril/", views.ayril, name="ayril"),
]
