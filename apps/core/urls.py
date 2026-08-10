from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.anasayfa, name="home"),
    path("panel/", views.panel, name="dashboard"),
    path("tema/", views.tema_degistir, name="tema_degistir"),
    path("cevrimdisi/", views.cevrimdisi, name="cevrimdisi"),
    # --- Ana ekrana eklenebilir uygulama (PWA) -----------------------------
    # İkisi de statik dosya olarak değil, görünüm olarak sunuluyor:
    #
    # sw.js: servis çalışanının yetki alanı (scope) bulunduğu klasörle
    #   sınırlı. /static/js/sw.js olsaydı yalnızca /static/js/ altını
    #   yönetebilirdi; tüm siteyi kapsaması için kökte olması şart.
    #
    # manifest: nginx'in mime.types tablosunda .webmanifest uzantısı
    #   bulunmuyor; statik sunulsa "application/octet-stream" olarak iner ve
    #   tarayıcı manifesti yok sayar. Görünümden sunulunca içerik türünü
    #   kendimiz veriyoruz.
    path("sw.js", views.servis_calisani, name="servis_calisani"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    # --- Arama motorları ---------------------------------------------------
    # Favicon ve logo KÖKTEN, karma içermeyen kararlı adreslerden sunuluyor:
    # Google arama sonucundaki site simgesini kararlı bir adresten okuyor ve
    # botların çoğu doğrudan /favicon.ico deniyor.
    path("favicon.ico", views.favicon, name="favicon"),
    path("logo.png", views.logo, name="logo"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
    # Korumalı dosya sunumu. Yol bilgisi değil, veritabanı kimliği alır;
    # bu sayede yol geçişi (path traversal) yapısal olarak imkânsızdır.
    path("dosya/avatar/<uuid:dosya_id>/", views.avatar_dosyasi, name="avatar_dosyasi"),
    path("dosya/mac/<uuid:dosya_id>/", views.mac_fotografi, name="mac_fotografi"),
]
