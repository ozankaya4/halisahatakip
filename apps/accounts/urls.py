from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("duzenle/", views.profil_duzenle, name="profil_duzenle"),
    # Play Store, hesap açtıran uygulamalarda hesap silme yolu zorunlu tutuyor.
    path("hesabimi-sil/", views.hesabimi_sil, name="hesabimi_sil"),
    path("<int:kullanici_id>/", views.profil, name="profil"),
]
