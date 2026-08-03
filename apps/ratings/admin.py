from django.contrib import admin

from .models import Puan


@admin.register(Puan)
class PuanAdmin(admin.ModelAdmin):
    """
    Puanlar arayüzde anonimdir. Burada "puanlayan" alanı görünür, çünkü nihai
    yönetici kötüye kullanım (örn. birine kasten 1 verme) incelemesi
    yapabilmelidir. Bu bilinçli bir istisnadır.
    """

    list_display = ("puanlanan", "deger", "mac", "olusturulma")
    list_filter = ("deger", "mac__grup", "olusturulma")
    search_fields = (
        "puanlanan__email",
        "puanlanan__ad_soyad",
        "puanlayan__email",
        "puanlayan__ad_soyad",
    )
    autocomplete_fields = ("mac", "puanlayan", "puanlanan")
    readonly_fields = ("olusturulma", "guncellenme")
