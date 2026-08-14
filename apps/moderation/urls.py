from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("fotograf/<int:foto_id>/bildir/", views.fotograf_bildir, name="fotograf_bildir"),
    path("sohbet/<uuid:genel_id>/bildir/", views.mesaj_bildir, name="mesaj_bildir"),
    path("grup/<uuid:genel_id>/", views.liste, name="liste"),
    path("grup/<uuid:genel_id>/<int:sikayet_id>/karar/", views.karar, name="karar"),
]
