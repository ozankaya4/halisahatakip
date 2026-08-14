from django.contrib import admin

from .models import Sikayet


@admin.register(Sikayet)
class SikayetAdmin(admin.ModelAdmin):
    list_display = ("olusturulma", "grup", "tur", "sebep", "durum", "bildiren")
    list_filter = ("durum", "tur", "sebep")
    search_fields = ("grup__ad", "bildiren__email", "aciklama")
    readonly_fields = ("olusturulma", "guncellenme", "mesaj_metni")
    autocomplete_fields = ()
