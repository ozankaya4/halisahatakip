from django.urls import path

from . import views

app_name = "ratings"

urlpatterns = [
    path("mac/<int:mac_id>/", views.puanla, name="puanla"),
    path("mac/<int:mac_id>/sonuclar/", views.sonuclar, name="sonuclar"),
    path("grup/<uuid:genel_id>/siralama/", views.siralama, name="siralama"),
    path("grup/<uuid:genel_id>/oy-incelemesi/", views.oy_incelemesi, name="oy_incelemesi"),
]
