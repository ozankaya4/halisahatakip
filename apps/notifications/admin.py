from django.contrib import admin

from .models import Bildirim


@admin.register(Bildirim)
class BildirimAdmin(admin.ModelAdmin):
    list_display = ("alici", "tur", "baslik", "okundu", "olusturulma")
    list_filter = ("tur", "okundu", "olusturulma")
    search_fields = ("alici__email", "alici__ad_soyad", "baslik", "mesaj")
    readonly_fields = ("olusturulma",)
    date_hierarchy = "olusturulma"
