"""Kök URL yapılandırması."""

from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views

# Yönetim panelini tahmin edilebilir /admin/ yolundan kaydırmak, otomatik
# tarayıcı botlarının gürültüsünü belirgin biçimde azaltır.
admin.site.site_header = "Halısaha Takip Yönetimi"
admin.site.site_title = "Halısaha Takip"
admin.site.index_title = "Yönetim"

urlpatterns = [
    path("yonetim/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("hesap/", include("allauth.urls")),
    path("profil/", include("apps.accounts.urls")),
    path("gruplar/", include("apps.groups.urls")),
    path("maclar/", include("apps.matches.urls")),
    path("puanlar/", include("apps.ratings.urls")),
    path("sohbet/", include("apps.chat.urls")),
    path("bildir/", include("apps.moderation.urls")),
    path("bildirimler/", include("apps.notifications.urls")),
]

handler403 = core_views.hata_403
handler404 = core_views.hata_404
handler500 = core_views.hata_500
