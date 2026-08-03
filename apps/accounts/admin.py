from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as TemelUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import Profil, User


class KullaniciOlusturmaFormu(UserCreationForm):
    class Meta:
        model = User
        fields = ("email", "ad_soyad")


class KullaniciDegistirmeFormu(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class ProfilSatiri(admin.StackedInline):
    model = Profil
    can_delete = False
    readonly_fields = ("ortalama_puan", "puan_sayisi", "oynanan_mac", "avatar_id")
    extra = 0


@admin.register(User)
class UserAdmin(TemelUserAdmin):
    add_form = KullaniciOlusturmaFormu
    form = KullaniciDegistirmeFormu
    change_password_form = AdminPasswordChangeForm
    model = User
    inlines = [ProfilSatiri]

    list_display = ("email", "ad_soyad", "is_active", "is_staff", "is_superuser", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser", "date_joined")
    search_fields = ("email", "ad_soyad")
    ordering = ("email",)
    readonly_fields = ("date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Kişisel bilgiler", {"fields": ("ad_soyad",)}),
        (
            "Yetkiler",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Tarihler", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "ad_soyad", "password1", "password2"),
            },
        ),
    )


@admin.register(Profil)
class ProfilAdmin(admin.ModelAdmin):
    list_display = ("kullanici", "mevki", "forma_no", "ortalama_puan", "puan_sayisi", "oynanan_mac")
    list_filter = ("mevki",)
    search_fields = ("kullanici__email", "kullanici__ad_soyad")
    readonly_fields = ("avatar_id", "ortalama_puan", "puan_sayisi", "oynanan_mac")

    @admin.action(description="Seçili profillerin istatistiklerini yeniden hesapla")
    def istatistik_yenile(self, request, queryset):
        for profil in queryset:
            profil.istatistikleri_yenile()
        self.message_user(request, f"{queryset.count()} profil güncellendi.")

    actions = ["istatistik_yenile"]
