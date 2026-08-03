"""Grup, üyelik ve davet bağlantısı modelleri."""

from __future__ import annotations

import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.models import ZamanDamgaliModel

# Ham davet jetonunun uzunluğu (bayt). 32 bayt = 256 bit entropi.
JETON_BAYT = 32


def jeton_ozeti(ham_jeton: str) -> str:
    """
    Davet jetonunun veritabanında saklanan biçimi.

    Jetonun kendisi asla kaydedilmez. Veritabanı sızsa bile eldeki özetlerden
    çalışan davet bağlantısı üretilemez. Jeton yüksek entropili ve rastgele
    olduğu için tuzsuz SHA-256 burada yeterlidir (parolalardan farklı olarak
    sözlük saldırısına konu değildir).
    """
    return hashlib.sha256(ham_jeton.encode("utf-8")).hexdigest()


class Grup(ZamanDamgaliModel):
    ad = models.CharField("grup adı", max_length=60)
    aciklama = models.CharField("açıklama", max_length=200, blank=True)
    kurucu = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="kurdugu_gruplar",
        verbose_name="kurucu",
    )
    # URL'lerde birincil anahtar yerine bu kullanılır (numara sayımını engeller).
    genel_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        verbose_name = "grup"
        verbose_name_plural = "gruplar"
        ordering = ["ad"]

    def __str__(self) -> str:
        return self.ad

    def get_absolute_url(self) -> str:
        return reverse("groups:detay", kwargs={"genel_id": self.genel_id})

    # --- yetki yardımcıları ------------------------------------------------
    def uyelik(self, kullanici) -> "Uyelik | None":
        if not kullanici or not kullanici.is_authenticated:
            return None
        return self.uyelikler.filter(kullanici=kullanici).first()

    def uye_mi(self, kullanici) -> bool:
        if not kullanici or not kullanici.is_authenticated:
            return False
        return self.uyelikler.filter(
            kullanici=kullanici, durum=Uyelik.Durum.ONAYLI
        ).exists()

    def yonetici_mi(self, kullanici) -> bool:
        """Nihai yönetici (superuser) her grupta yöneticidir."""
        if not kullanici or not kullanici.is_authenticated:
            return False
        if kullanici.is_superuser:
            return True
        return self.uyelikler.filter(
            kullanici=kullanici,
            durum=Uyelik.Durum.ONAYLI,
            rol=Uyelik.Rol.YONETICI,
        ).exists()

    @property
    def onayli_uyelikler(self):
        return self.uyelikler.filter(durum=Uyelik.Durum.ONAYLI).select_related(
            "kullanici", "kullanici__profil"
        )

    @property
    def uye_sayisi(self) -> int:
        return self.uyelikler.filter(durum=Uyelik.Durum.ONAYLI).count()

    @property
    def bekleyen_sayisi(self) -> int:
        return self.uyelikler.filter(durum=Uyelik.Durum.BEKLIYOR).count()

    @property
    def yonetici_sayisi(self) -> int:
        return self.uyelikler.filter(
            durum=Uyelik.Durum.ONAYLI, rol=Uyelik.Rol.YONETICI
        ).count()


class Uyelik(ZamanDamgaliModel):
    class Rol(models.TextChoices):
        UYE = "uye", "Üye"
        YONETICI = "yonetici", "Yönetici"

    class Durum(models.TextChoices):
        BEKLIYOR = "bekliyor", "Onay bekliyor"
        ONAYLI = "onayli", "Onaylı"
        REDDEDILDI = "reddedildi", "Reddedildi"
        AYRILDI = "ayrildi", "Ayrıldı"

    grup = models.ForeignKey(
        Grup, on_delete=models.CASCADE, related_name="uyelikler", verbose_name="grup"
    )
    kullanici = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="uyelikler",
        verbose_name="kullanıcı",
    )
    rol = models.CharField("rol", max_length=10, choices=Rol.choices, default=Rol.UYE)
    durum = models.CharField(
        "durum", max_length=12, choices=Durum.choices, default=Durum.BEKLIYOR
    )
    katilma_notu = models.CharField("katılma notu", max_length=200, blank=True)
    onaylayan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onayladigi_uyelikler",
        verbose_name="onaylayan",
    )
    karar_tarihi = models.DateTimeField("karar tarihi", null=True, blank=True)

    class Meta:
        verbose_name = "üyelik"
        verbose_name_plural = "üyelikler"
        constraints = [
            models.UniqueConstraint(
                fields=["grup", "kullanici"], name="benzersiz_grup_uyeligi"
            )
        ]
        ordering = ["-rol", "kullanici__ad_soyad"]
        indexes = [models.Index(fields=["grup", "durum"])]

    def __str__(self) -> str:
        return f"{self.kullanici} · {self.grup} ({self.get_durum_display()})"

    @property
    def yonetici_mi(self) -> bool:
        return self.durum == self.Durum.ONAYLI and self.rol == self.Rol.YONETICI

    def onayla(self, onaylayan) -> None:
        self.durum = self.Durum.ONAYLI
        self.onaylayan = onaylayan
        self.karar_tarihi = timezone.now()
        self.save(update_fields=["durum", "onaylayan", "karar_tarihi", "guncellenme"])

    def reddet(self, reddeden) -> None:
        self.durum = self.Durum.REDDEDILDI
        self.onaylayan = reddeden
        self.karar_tarihi = timezone.now()
        self.save(update_fields=["durum", "onaylayan", "karar_tarihi", "guncellenme"])


class DavetBagi(ZamanDamgaliModel):
    """
    Gruba katılma bağlantısı.

    Ham jeton yalnızca oluşturulduğu anda bir kez gösterilir; veritabanında
    özeti tutulur. Bağlantıyı kullanan kişi doğrudan üye olmaz — üyeliği
    "onay bekliyor" durumunda açılır ve bir yöneticinin onayı gerekir.
    """

    grup = models.ForeignKey(
        Grup, on_delete=models.CASCADE, related_name="davetler", verbose_name="grup"
    )
    olusturan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="olusturdugu_davetler",
        verbose_name="oluşturan",
    )
    jeton_ozet = models.CharField(
        "jeton özeti", max_length=64, unique=True, db_index=True, editable=False
    )
    etiket = models.CharField("etiket", max_length=60, blank=True)
    son_kullanma = models.DateTimeField("son kullanma", db_index=True)
    max_kullanim = models.PositiveSmallIntegerField("azami kullanım", default=25)
    kullanim_sayisi = models.PositiveSmallIntegerField("kullanım sayısı", default=0)
    iptal_edildi = models.BooleanField("iptal edildi", default=False)

    class Meta:
        verbose_name = "davet bağlantısı"
        verbose_name_plural = "davet bağlantıları"
        ordering = ["-olusturulma"]

    def __str__(self) -> str:
        return f"{self.grup} daveti ({self.etiket or 'etiketsiz'})"

    @classmethod
    def olustur(cls, grup, olusturan, gun: int, max_kullanim: int, etiket: str = ""):
        """Yeni davet üretir. (kayıt, ham_jeton) döndürür — jeton bir daha alınamaz."""
        ham = secrets.token_urlsafe(JETON_BAYT)
        kayit = cls.objects.create(
            grup=grup,
            olusturan=olusturan,
            jeton_ozet=jeton_ozeti(ham),
            etiket=etiket[:60],
            son_kullanma=timezone.now() + timezone.timedelta(days=gun),
            max_kullanim=max_kullanim,
        )
        return kayit, ham

    @classmethod
    def jetondan_bul(cls, ham_jeton: str) -> "DavetBagi | None":
        if not ham_jeton:
            return None
        return (
            cls.objects.select_related("grup")
            .filter(jeton_ozet=jeton_ozeti(ham_jeton))
            .first()
        )

    @property
    def gecerli_mi(self) -> bool:
        return (
            not self.iptal_edildi
            and self.son_kullanma > timezone.now()
            and self.kullanim_sayisi < self.max_kullanim
        )

    @property
    def durum_metni(self) -> str:
        if self.iptal_edildi:
            return "İptal edildi"
        if self.son_kullanma <= timezone.now():
            return "Süresi doldu"
        if self.kullanim_sayisi >= self.max_kullanim:
            return "Kullanım hakkı bitti"
        return "Geçerli"

    def kullanildi(self) -> None:
        # F() ile artırmak eşzamanlı isteklerde sayacın kaçmasını önler.
        DavetBagi.objects.filter(pk=self.pk).update(
            kullanim_sayisi=models.F("kullanim_sayisi") + 1
        )
