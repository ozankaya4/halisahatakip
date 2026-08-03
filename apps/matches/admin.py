from django.contrib import admin

from .models import Katilim, Mac, MacFotografi


class KatilimSatiri(admin.TabularInline):
    model = Katilim
    extra = 0
    autocomplete_fields = ("kullanici",)


class FotografSatiri(admin.TabularInline):
    model = MacFotografi
    extra = 0
    readonly_fields = ("dosya_id", "yukleyen", "olusturulma")


@admin.register(Mac)
class MacAdmin(admin.ModelAdmin):
    list_display = ("grup", "baslangic", "konum", "yoklama_acik", "iptal", "olusturan")
    list_filter = ("grup", "iptal", "yoklama_acik", "baslangic")
    search_fields = ("grup__ad", "konum", "notlar")
    date_hierarchy = "baslangic"
    autocomplete_fields = ("grup", "olusturan")
    inlines = [KatilimSatiri, FotografSatiri]


@admin.register(Katilim)
class KatilimAdmin(admin.ModelAdmin):
    list_display = ("kullanici", "mac", "yanit", "katildi")
    list_filter = ("yanit", "katildi", "mac__grup")
    search_fields = ("kullanici__email", "kullanici__ad_soyad")
    autocomplete_fields = ("kullanici", "mac")


@admin.register(MacFotografi)
class MacFotografiAdmin(admin.ModelAdmin):
    list_display = ("mac", "yukleyen", "aciklama", "olusturulma")
    list_filter = ("mac__grup",)
    readonly_fields = ("dosya_id", "olusturulma", "guncellenme")
    autocomplete_fields = ("mac", "yukleyen")
