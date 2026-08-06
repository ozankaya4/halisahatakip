"""Kullanıcı ve profil modelleri."""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.models import ZamanDamgaliModel


def avatar_yolu(ornek: "Profil", dosya_adi: str) -> str:
    """Dosya adı çağıran tarafça UUID'ye çevrilmiş olarak gelir."""
    return f"avatarlar/{dosya_adi}"


class KullaniciYoneticisi(BaseUserManager):
    use_in_migrations = True

    def _olustur(self, email, password, **ekstra):
        if not email:
            raise ValueError("E-posta adresi zorunludur.")
        email = self.normalize_email(email).lower()
        kullanici = self.model(email=email, **ekstra)
        kullanici.set_password(password)
        kullanici.full_clean(exclude=["password", "last_login"])
        kullanici.save(using=self._db)
        return kullanici

    def create_user(self, email, password=None, **ekstra):
        ekstra.setdefault("is_staff", False)
        ekstra.setdefault("is_superuser", False)
        return self._olustur(email, password, **ekstra)

    def create_superuser(self, email, password=None, **ekstra):
        ekstra.setdefault("is_staff", True)
        ekstra.setdefault("is_superuser", True)
        ekstra.setdefault("is_active", True)
        if ekstra.get("is_staff") is not True:
            raise ValueError("Süper kullanıcı is_staff=True olmalıdır.")
        if ekstra.get("is_superuser") is not True:
            raise ValueError("Süper kullanıcı is_superuser=True olmalıdır.")
        return self._olustur(email, password, **ekstra)


class User(AbstractBaseUser, PermissionsMixin):
    """Kullanıcı adı yerine e-posta ile çalışan kullanıcı modeli."""

    email = models.EmailField("e-posta", unique=True, db_index=True)
    ad_soyad = models.CharField("ad soyad", max_length=80, blank=True)
    is_active = models.BooleanField("aktif", default=True)
    is_staff = models.BooleanField("yönetim paneline erişebilir", default=False)
    date_joined = models.DateTimeField("katılma tarihi", default=timezone.now)

    objects = KullaniciYoneticisi()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "kullanıcı"
        verbose_name_plural = "kullanıcılar"
        ordering = ["ad_soyad", "email"]

    def __str__(self) -> str:
        return self.ad_soyad or self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower().strip()
        super().save(*args, **kwargs)

    @property
    def gorunen_ad(self) -> str:
        """Arayüzde gösterilecek ad. Ad girilmemişse e-postanın yerel kısmı."""
        if self.ad_soyad.strip():
            return self.ad_soyad.strip()
        return self.email.split("@")[0]

    @property
    def bas_harfler(self) -> str:
        parcalar = [p for p in self.gorunen_ad.split() if p]
        if not parcalar:
            return "?"
        if len(parcalar) == 1:
            return parcalar[0][:2].upper()
        return (parcalar[0][0] + parcalar[-1][0]).upper()

    def get_full_name(self) -> str:
        return self.gorunen_ad

    def get_short_name(self) -> str:
        return self.gorunen_ad.split()[0] if self.gorunen_ad else self.email


class Mevki(models.TextChoices):
    BELIRTILMEMIS = "", "Belirtilmemiş"
    KALECI = "kaleci", "Kaleci"
    DEFANS = "defans", "Defans"
    ORTA_SAHA = "orta_saha", "Orta saha"
    FORVET = "forvet", "Forvet"


class Profil(ZamanDamgaliModel):
    """
    Herkese açık oyuncu profili.

    Puan ortalaması burada önbelleklenir; her profil görüntülemesinde tüm
    puanları toplamak yerine puan kaydedildiğinde yeniden hesaplanır.
    """

    kullanici = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="profil", verbose_name="kullanıcı"
    )
    avatar = models.ImageField(
        "profil fotoğrafı", upload_to=avatar_yolu, blank=True, null=True
    )
    # URL'de bu kimlik kullanılır; dosya yolu asla dışarı sızmaz.
    avatar_id = models.UUIDField(
        "avatar kimliği", default=uuid.uuid4, unique=True, editable=False
    )
    mevki = models.CharField(
        "mevki", max_length=20, choices=Mevki.choices, blank=True, default=""
    )
    forma_no = models.PositiveSmallIntegerField("forma numarası", blank=True, null=True)
    hakkinda = models.CharField("kısa not", max_length=160, blank=True)

    # Önbelleğe alınan istatistikler
    ortalama_puan = models.DecimalField(
        "ortalama puan", max_digits=4, decimal_places=2, null=True, blank=True
    )
    puan_sayisi = models.PositiveIntegerField("aldığı puan sayısı", default=0)
    oynanan_mac = models.PositiveIntegerField("oynadığı maç", default=0)

    class Meta:
        verbose_name = "profil"
        verbose_name_plural = "profiller"

    def __str__(self) -> str:
        return f"{self.kullanici.gorunen_ad} profili"

    def get_absolute_url(self) -> str:
        return reverse("accounts:profil", kwargs={"kullanici_id": self.kullanici_id})

    @property
    def avatar_url(self) -> str | None:
        if not self.avatar:
            return None
        return reverse("core:avatar_dosyasi", kwargs={"dosya_id": self.avatar_id})

    @property
    def ortalama_gosterilsin(self) -> bool:
        """Az sayıda oyla oluşan ortalama yanıltıcıdır; eşiğin altında gizlenir."""
        from django.conf import settings

        return (
            self.ortalama_puan is not None
            and self.puan_sayisi >= settings.RATING_MIN_VOTES_TO_DISPLAY
        )

    def istatistikleri_yenile(self, kaydet: bool = True) -> None:
        """
        Puan ortalamasını ve maç sayısını puan kayıtlarından yeniden hesaplar.

        DİKKAT: Buradaki ortalama **tüm grupların toplamıdır** ve artık
        arayüzde gösterilmez; yalnızca yönetim panelinde bilgi amaçlıdır.
        Herkese açık ortalamalar grup bazında hesaplanır
        (apps/ratings/hesaplar.py), çünkü küresel tek bir ortalama olsaydı
        kişi kendi grubunu kurup kendine puan vererek onu şişirebilirdi.

        İptal edilen maçların puanları hiçbir hesaba katılmaz.
        """
        from django.db.models import Avg, Count

        from apps.matches.models import Katilim
        from apps.ratings.models import Puan

        ozet = Puan.objects.filter(
            puanlanan=self.kullanici, mac__iptal=False, karantinada=False
        ).aggregate(ortalama=Avg("deger"), adet=Count("id"))
        self.ortalama_puan = (
            round(ozet["ortalama"], 2) if ozet["ortalama"] is not None else None
        )
        self.puan_sayisi = ozet["adet"] or 0
        self.oynanan_mac = Katilim.objects.filter(
            kullanici=self.kullanici, katildi=True, mac__iptal=False
        ).count()
        if kaydet:
            self.save(
                update_fields=[
                    "ortalama_puan",
                    "puan_sayisi",
                    "oynanan_mac",
                    "guncellenme",
                ]
            )
