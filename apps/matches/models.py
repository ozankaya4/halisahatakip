"""Maç, yoklama (anket) ve maç fotoğrafı modelleri."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.models import ZamanDamgaliModel


def mac_foto_yolu(ornek: "MacFotografi", dosya_adi: str) -> str:
    """Dosya adı çağıran tarafça UUID'ye çevrilmiş olarak gelir."""
    return f"mac-fotograflari/{ornek.mac.grup_id}/{dosya_adi}"


class Mac(ZamanDamgaliModel):
    class Takim(models.TextChoices):
        A = "a", "A Takımı"
        B = "b", "B Takımı"

    grup = models.ForeignKey(
        "groups.Grup", on_delete=models.CASCADE, related_name="maclar", verbose_name="grup"
    )
    baslangic = models.DateTimeField("tarih ve saat", db_index=True)
    konum = models.CharField("saha / konum", max_length=120, blank=True)
    notlar = models.CharField("not", max_length=200, blank=True)
    sure_dakika = models.PositiveSmallIntegerField("süre (dakika)", default=60)

    olusturan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="olusturdugu_maclar",
        verbose_name="oluşturan",
    )

    yoklama_acik = models.BooleanField("yoklama açık", default=True)
    yoklama_son = models.DateTimeField("yoklama son tarihi", null=True, blank=True)
    iptal = models.BooleanField("iptal edildi", default=False)

    # Maç sonucu. İkisi birden girilene kadar skor "girilmemiş" sayılır;
    # 0-0 geçerli bir sonuç olduğu için varsayılan 0 değil None.
    skor_a = models.PositiveSmallIntegerField("A takımı skoru", null=True, blank=True)
    skor_b = models.PositiveSmallIntegerField("B takımı skoru", null=True, blank=True)

    class Meta:
        verbose_name = "maç"
        verbose_name_plural = "maçlar"
        ordering = ["-baslangic"]
        indexes = [models.Index(fields=["grup", "-baslangic"])]

    def __str__(self) -> str:
        return f"{self.grup.ad} · {timezone.localtime(self.baslangic):%d.%m.%Y %H:%M}"

    def get_absolute_url(self) -> str:
        return reverse("matches:detay", kwargs={"mac_id": self.pk})

    # --- zaman durumu ------------------------------------------------------
    @property
    def gecmis_mi(self) -> bool:
        return self.baslangic < timezone.now()

    @property
    def bitis(self):
        return self.baslangic + timezone.timedelta(minutes=self.sure_dakika)

    @property
    def yoklama_alinabilir(self) -> bool:
        if self.iptal or not self.yoklama_acik:
            return False
        son = self.yoklama_son or self.baslangic
        return timezone.now() < son

    @property
    def puanlama_bitis(self):
        return self.baslangic + timezone.timedelta(days=settings.RATING_WINDOW_DAYS)

    @property
    def puanlama_acik(self) -> bool:
        """Puanlama maç saatinde açılır, RATING_WINDOW_DAYS gün sonra kapanır."""
        if self.iptal:
            return False
        return self.baslangic <= timezone.now() <= self.puanlama_bitis

    @property
    def puanlama_durumu(self) -> str:
        if self.iptal:
            return "İptal edildi"
        simdi = timezone.now()
        if simdi < self.baslangic:
            return "Maç henüz oynanmadı"
        if simdi > self.puanlama_bitis:
            return "Puanlama süresi doldu"
        return "Puanlama açık"

    # --- sonuç -------------------------------------------------------------
    @property
    def skor_girildi_mi(self) -> bool:
        """0-0 geçerli bir sonuç; bu yüzden None kontrolü yapılıyor."""
        return self.skor_a is not None and self.skor_b is not None

    @property
    def berabere_mi(self) -> bool:
        return self.skor_girildi_mi and self.skor_a == self.skor_b

    @property
    def kazanan_takim(self) -> str | None:
        """Kazanan takımın kodu ("a"/"b"). Beraberlikte ve skor yokken None."""
        if not self.skor_girildi_mi or self.berabere_mi:
            return None
        return self.Takim.A if self.skor_a > self.skor_b else self.Takim.B

    @property
    def skor_yazisi(self) -> str:
        return f"{self.skor_a} - {self.skor_b}" if self.skor_girildi_mi else "—"

    def takim_katilimlari(self, takim: str):
        return self.oynayan_katilimlar().filter(takim=takim)

    @property
    def takimlar_kurulmus_mu(self) -> bool:
        """En az bir oyuncu her iki takıma da atanmış mı?"""
        takimlar = set(
            self.oynayan_katilimlar()
            .exclude(takim="")
            .values_list("takim", flat=True)
        )
        return {self.Takim.A, self.Takim.B} <= takimlar

    # --- katılım -----------------------------------------------------------
    def oynayan_katilimlar(self):
        """
        Maçta sahaya çıkmış sayılan katılım kayıtları.

        Yönetici kadroyu elle işaretlediyse (katildi=True/False) o karar
        geçerlidir; işaretlenmemişse "Geliyorum" yanıtı esas alınır.
        """
        return self.katilimlar.filter(
            models.Q(katildi=True)
            | models.Q(katildi__isnull=True, yanit=Katilim.Yanit.GELIYORUM)
        ).select_related("kullanici", "kullanici__profil")

    def oynayan_kullanici_idleri(self) -> set[int]:
        return set(self.oynayan_katilimlar().values_list("kullanici_id", flat=True))

    def kullanici_puanlayabilir(self, kullanici) -> bool:
        """Yalnızca maçta oynayanlar puan verebilir (nihai yönetici dâhil değil)."""
        if not kullanici or not kullanici.is_authenticated:
            return False
        if not self.puanlama_acik:
            return False
        if not settings.RATING_REQUIRES_ATTENDANCE:
            return self.grup.uye_mi(kullanici)
        return kullanici.pk in self.oynayan_kullanici_idleri()

    def sayim(self) -> dict[str, int]:
        sonuc = {"geliyorum": 0, "yokum": 0, "belki": 0, "yanitsiz": 0}
        for katilim in self.katilimlar.all():
            if katilim.yanit in sonuc:
                sonuc[katilim.yanit] += 1
        sonuc["yanitsiz"] = max(self.grup.uye_sayisi - sum(sonuc.values()), 0)
        return sonuc


class Katilim(ZamanDamgaliModel):
    """Yoklama yanıtı ve gerçek katılım."""

    class Yanit(models.TextChoices):
        GELIYORUM = "geliyorum", "Geliyorum"
        YOKUM = "yokum", "Yokum"
        BELKI = "belki", "Belki"

    mac = models.ForeignKey(
        Mac, on_delete=models.CASCADE, related_name="katilimlar", verbose_name="maç"
    )
    kullanici = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="katilimlar",
        verbose_name="kullanıcı",
    )
    yanit = models.CharField("yanıt", max_length=10, choices=Yanit.choices)
    # None: yönetici kadroyu işaretlememiş, yanıt esas alınır.
    katildi = models.BooleanField("sahaya çıktı", null=True, blank=True, default=None)
    # Boş: takım atanmamış. Yalnızca sahaya çıkanlara takım verilir.
    takim = models.CharField(
        "takım", max_length=1, choices=Mac.Takim.choices, blank=True, default=""
    )

    # --- Dizilim ----------------------------------------------------------
    # Sahadaki konum, sahanın YÜZDESİ olarak (0-100). Piksel değil: saha
    # telefonda ve masaüstünde farklı boyutlarda çiziliyor, yüzde her ikisinde
    # de aynı yere denk geliyor.
    # None: yönetici bu oyuncuyu henüz yerleştirmemiş.
    poz_x = models.PositiveSmallIntegerField("saha konumu X", null=True, blank=True)
    poz_y = models.PositiveSmallIntegerField("saha konumu Y", null=True, blank=True)

    # --- Maç istatistikleri ------------------------------------------------
    # Görünürlükleri grup ayarına bağlı (bkz. Grup.gol_gosterilsin vb.);
    # veri her hâlükârda tutulur, yalnızca gösterilip gösterilmediği değişir.
    gol = models.PositiveSmallIntegerField("gol", default=0)
    asist = models.PositiveSmallIntegerField("asist", default=0)
    sari_kart = models.PositiveSmallIntegerField("sarı kart", default=0)
    kirmizi_kart = models.BooleanField("kırmızı kart", default=False)

    class Meta:
        verbose_name = "katılım"
        verbose_name_plural = "katılımlar"
        constraints = [
            models.UniqueConstraint(fields=["mac", "kullanici"], name="benzersiz_katilim")
        ]
        indexes = [models.Index(fields=["mac", "yanit"])]

    def __str__(self) -> str:
        return f"{self.kullanici} · {self.mac} · {self.get_yanit_display()}"

    @property
    def oynadi_mi(self) -> bool:
        if self.katildi is not None:
            return self.katildi
        return self.yanit == self.Yanit.GELIYORUM


class MacFotografi(ZamanDamgaliModel):
    """
    Maçtan fotoğraf.

    Dosya her zaman yeniden kodlanmış WEBP'tir (bkz. apps/core/images.py) ve
    yalnızca grubun onaylı üyelerine, yetki kontrolünden geçen bir görünüm
    üzerinden sunulur.
    """

    mac = models.ForeignKey(
        Mac, on_delete=models.CASCADE, related_name="fotograflar", verbose_name="maç"
    )
    dosya = models.ImageField("dosya", upload_to=mac_foto_yolu)
    dosya_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    yukleyen = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="yukledigi_fotograflar",
        verbose_name="yükleyen",
    )
    aciklama = models.CharField("açıklama", max_length=120, blank=True)

    class Meta:
        verbose_name = "maç fotoğrafı"
        verbose_name_plural = "maç fotoğrafları"
        ordering = ["olusturulma"]

    def __str__(self) -> str:
        return f"{self.mac} fotoğrafı"

    @property
    def url(self) -> str:
        return reverse("core:mac_fotografi", kwargs={"dosya_id": self.dosya_id})

    def delete(self, *args, **kwargs):
        # Kayıt silinince dosya diskte yetim kalmasın.
        dosya = self.dosya
        sonuc = super().delete(*args, **kwargs)
        if dosya:
            dosya.delete(save=False)
        return sonuc
