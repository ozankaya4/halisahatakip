from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.anasayfa, name="home"),
    path("panel/", views.panel, name="dashboard"),
    path("tema/", views.tema_degistir, name="tema_degistir"),
    # Korumalı dosya sunumu. Yol bilgisi değil, veritabanı kimliği alır;
    # bu sayede yol geçişi (path traversal) yapısal olarak imkânsızdır.
    path("dosya/avatar/<uuid:dosya_id>/", views.avatar_dosyasi, name="avatar_dosyasi"),
    path("dosya/mac/<uuid:dosya_id>/", views.mac_fotografi, name="mac_fotografi"),
]
