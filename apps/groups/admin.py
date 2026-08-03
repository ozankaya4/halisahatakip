from django.contrib import admin

from .models import DavetBagi, Grup, Uyelik


class UyelikSatiri(admin.TabularInline):
    model = Uyelik
    extra = 0
    fields = ("kullanici", "rol", "durum", "onaylayan", "karar_tarihi")
    readonly_fields = ("karar_tarihi",)
    autocomplete_fields = ("kullanici", "onaylayan")


@admin.register(Grup)
class GrupAdmin(admin.ModelAdmin):
    list_display = ("ad", "kurucu", "uye_sayisi", "bekleyen_sayisi", "olusturulma")
    search_fields = ("ad", "aciklama", "kurucu__email")
    readonly_fields = ("genel_id", "olusturulma", "guncellenme")
    inlines = [UyelikSatiri]
    autocomplete_fields = ("kurucu",)


@admin.register(Uyelik)
class UyelikAdmin(admin.ModelAdmin):
    list_display = ("kullanici", "grup", "rol", "durum", "onaylayan", "karar_tarihi")
    list_filter = ("rol", "durum", "grup")
    search_fields = ("kullanici__email", "kullanici__ad_soyad", "grup__ad")
    autocomplete_fields = ("kullanici", "grup", "onaylayan")


@admin.register(DavetBagi)
class DavetBagiAdmin(admin.ModelAdmin):
    """Ham jeton hiçbir yerde saklanmadığı için panelde de gösterilemez."""

    list_display = (
        "grup",
        "etiket",
        "durum_metni",
        "kullanim_sayisi",
        "max_kullanim",
        "son_kullanma",
        "olusturan",
    )
    list_filter = ("iptal_edildi", "grup")
    search_fields = ("grup__ad", "etiket")
    readonly_fields = ("jeton_ozet", "kullanim_sayisi", "olusturulma", "guncellenme")
    autocomplete_fields = ("grup", "olusturan")
