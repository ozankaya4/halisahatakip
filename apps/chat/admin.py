from django.contrib import admin

from .models import AnahtarCifti, AnahtarPaketi, GrupAnahtari, Mesaj


@admin.register(AnahtarCifti)
class AnahtarCiftiAdmin(admin.ModelAdmin):
    """Özel anahtar burada da şifrelidir; panelden okunamaz."""

    list_display = ("kullanici", "parmak_izi", "yineleme", "olusturulma")
    search_fields = ("kullanici__email", "kullanici__ad_soyad", "parmak_izi")
    readonly_fields = (
        "kullanici",
        "acik_anahtar",
        "sifreli_ozel_anahtar",
        "tuz",
        "iv",
        "yineleme",
        "parmak_izi",
        "olusturulma",
        "guncellenme",
    )

    def has_add_permission(self, request):
        return False


@admin.register(GrupAnahtari)
class GrupAnahtariAdmin(admin.ModelAdmin):
    list_display = ("grup", "surum", "aktif", "dondurulmeli", "olusturan", "olusturulma")
    list_filter = ("aktif", "dondurulmeli", "grup")
    readonly_fields = ("olusturulma", "guncellenme")

    def has_add_permission(self, request):
        return False


@admin.register(AnahtarPaketi)
class AnahtarPaketiAdmin(admin.ModelAdmin):
    list_display = ("uye", "grup_anahtari", "olusturulma")
    list_filter = ("grup_anahtari__grup",)
    readonly_fields = ("grup_anahtari", "uye", "sarmalanmis", "olusturulma")

    def has_add_permission(self, request):
        return False


@admin.register(Mesaj)
class MesajAdmin(admin.ModelAdmin):
    """
    Mesaj içeriği uçtan uca şifrelidir — nihai yönetici dâhil kimse buradan
    okuyamaz. Panelde yalnızca meta veri (kim, ne zaman) görünür; kötüye
    kullanım ihbarında mesajı silebilmek için "silindi" alanı düzenlenebilir.
    """

    list_display = ("grup", "gonderen", "anahtar_surum", "olusturulma", "silindi")
    list_filter = ("grup", "silindi", "olusturulma")
    search_fields = ("gonderen__email", "gonderen__ad_soyad")
    readonly_fields = (
        "grup",
        "gonderen",
        "anahtar_surum",
        "sifreli_metin",
        "iv",
        "olusturulma",
    )
    date_hierarchy = "olusturulma"

    def has_add_permission(self, request):
        return False
