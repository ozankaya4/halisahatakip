"""Uygulama içi bildirimler."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Bildirim(models.Model):
    class Tur(models.TextChoices):
        KATILMA_ISTEGI = "katilma_istegi", "Katılma isteği"
        KATILMA_ONAYLANDI = "katilma_onaylandi", "Katılma onaylandı"
        KATILMA_REDDEDILDI = "katilma_reddedildi", "Katılma reddedildi"
        YONETICI_YAPILDI = "yonetici_yapildi", "Yönetici yapıldı"
        YENI_MAC = "yeni_mac", "Yeni maç"
        MAC_GUNCELLENDI = "mac_guncellendi", "Maç güncellendi"
        MAC_IPTAL = "mac_iptal", "Maç iptal edildi"
        YOKLAMA_ACILDI = "yoklama_acildi", "Yoklama açıldı"
        PUANLAMA_ACILDI = "puanlama_acildi", "Puanlama açıldı"
        GRUPTAN_CIKARILDI = "gruptan_cikarildi", "Gruptan çıkarıldı"
        SUPHELI_OYLAMA = "supheli_oylama", "Şüpheli oylama"
        PUANLARIN_SILINDI = "puanlarin_silindi", "Puanların silindi"
        MACIN_ADAMI = "macin_adami", "Maçın adamı"

    alici = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bildirimler",
        verbose_name="alıcı",
    )
    tur = models.CharField("tür", max_length=24, choices=Tur.choices)
    baslik = models.CharField("başlık", max_length=120)
    mesaj = models.CharField("mesaj", max_length=250, blank=True)
    # Yalnızca uygulama içi göreli yollar saklanır (açık yönlendirme riski yok).
    hedef_url = models.CharField("hedef", max_length=250, blank=True)
    okundu = models.BooleanField("okundu", default=False, db_index=True)
    olusturulma = models.DateTimeField("oluşturulma", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "bildirim"
        verbose_name_plural = "bildirimler"
        ordering = ["-olusturulma"]
        indexes = [models.Index(fields=["alici", "okundu", "-olusturulma"])]

    def __str__(self) -> str:
        return f"{self.alici} · {self.baslik}"

    @property
    def guvenli_url(self) -> str:
        """Şablonda kullanılan hedef. Dış bağlantılar sessizce yok sayılır."""
        yol = self.hedef_url or ""
        if yol.startswith("/") and not yol.startswith("//"):
            return yol
        return ""


def bildir(alici, tur: str, baslik: str, mesaj: str = "", hedef_url: str = "") -> Bildirim | None:
    """Tek bir kullanıcıya bildirim yazar. Kişinin kendi eylemi ise atlanır."""
    if alici is None or not getattr(alici, "pk", None):
        return None
    return Bildirim.objects.create(
        alici=alici,
        tur=tur,
        baslik=baslik[:120],
        mesaj=mesaj[:250],
        hedef_url=hedef_url[:250] if hedef_url.startswith("/") else "",
    )


def toplu_bildir(alicilar, tur: str, baslik: str, mesaj: str = "", hedef_url: str = "") -> int:
    """Birden çok kullanıcıya tek sorguda bildirim yazar."""
    alicilar = [a for a in alicilar if a is not None and getattr(a, "pk", None)]
    if not alicilar:
        return 0
    simdi = timezone.now()
    kayitlar = [
        Bildirim(
            alici=a,
            tur=tur,
            baslik=baslik[:120],
            mesaj=mesaj[:250],
            hedef_url=hedef_url[:250] if hedef_url.startswith("/") else "",
            olusturulma=simdi,
        )
        for a in alicilar
    ]
    Bildirim.objects.bulk_create(kayitlar, batch_size=200)
    return len(kayitlar)
