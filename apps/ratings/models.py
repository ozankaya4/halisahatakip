"""
Maç sonrası oyuncu puanları.

Seçilen kurallar:
  * Yalnızca maçta sahaya çıkanlar puan verebilir ve puan alabilir.
  * Kimse kendine puan veremez (veritabanı kısıtıyla da garanti altında).
  * Tek tek puanlar gizlidir; arayüzde yalnızca ortalama gösterilir.
  * Puanlama maç saatinde açılır, RATING_WINDOW_DAYS gün sonra kapanır.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Puan(models.Model):
    mac = models.ForeignKey(
        "matches.Mac", on_delete=models.CASCADE, related_name="puanlar", verbose_name="maç"
    )
    puanlayan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="verdigi_puanlar",
        verbose_name="puanlayan",
    )
    puanlanan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="aldigi_puanlar",
        verbose_name="puanlanan",
    )
    deger = models.PositiveSmallIntegerField(
        "puan", validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    olusturulma = models.DateTimeField("oluşturulma", auto_now_add=True)
    guncellenme = models.DateTimeField("güncellenme", auto_now=True)

    # Şüpheli oylama tespit edildiğinde işaretlenir. Karantinadaki puanlar
    # HİÇBİR ortalamaya girmez ama silinmez: yönetici inceleyip ya onaylar
    # (silinir) ya da serbest bırakır. Böylece dürüst bir oyuncunun puanları
    # yanlışlıkla yok edilmiş olmuyor.
    karantinada = models.BooleanField("karantinada", default=False, db_index=True)

    # Bu puanın kaç kez yazıldığı: ilk oy 1, bir düzeltme 2.
    # settings.RATING_MAX_WRITES sınırına gelince değer kilitlenir.
    # Yalnızca GERÇEK değişiklikler sayılır; aynı puanı tekrar kaydetmek
    # hak yakmaz (form herkesi birden gönderdiği için, tek bir oyuncuyu
    # düzelten kişi diğerlerinin hakkını da harcamış olurdu).
    yazim_sayisi = models.PositiveSmallIntegerField("yazım sayısı", default=1)

    class Meta:
        verbose_name = "puan"
        verbose_name_plural = "puanlar"
        constraints = [
            models.UniqueConstraint(
                fields=["mac", "puanlayan", "puanlanan"], name="mac_basina_tek_puan"
            ),
            # Kendine puan verme yasağı uygulama katmanında da var; burada
            # veritabanı seviyesinde de kapatıyoruz.
            models.CheckConstraint(
                condition=~models.Q(puanlayan=models.F("puanlanan")),
                name="kendine_puan_verilemez",
            ),
            models.CheckConstraint(
                condition=models.Q(deger__gte=1) & models.Q(deger__lte=10),
                name="puan_1_10_arasinda",
            ),
        ]
        indexes = [
            models.Index(fields=["puanlanan"]),
            models.Index(fields=["mac", "puanlanan"]),
        ]

    def __str__(self) -> str:
        # Puanlayan bilinçli olarak yazılmıyor; günlüklere bile sızmasın.
        return f"{self.puanlanan} · {self.mac} · {self.deger}/10"
