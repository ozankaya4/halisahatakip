from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("duzenle/", views.profil_duzenle, name="profil_duzenle"),
    path("<int:kullanici_id>/", views.profil, name="profil"),
]
