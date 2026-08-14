"""
İçerik şikâyetleri.

NEDEN VAR
---------
Uygulama kullanıcı içeriği taşıyor: maç fotoğrafları ve grup sohbeti. Google
Play, kullanıcı içeriği barındıran uygulamalarda üç şeyi birlikte arıyor:
yazılı bir kural (templates/core/kurallar.html), içeriği bildirme yolu (bu
uygulama) ve kaldırma yetkisi (grup yöneticisi).

ŞİFRELİ SOHBET NASIL BİLDİRİLİYOR
---------------------------------
Sunucu mesajları okuyamıyor (bkz. apps/chat/models.py). Bu yüzden mesaj
şikâyetinde metin, ŞİKÂYET EDEN KİŞİNİN cihazından geliyor: mesaj zaten onun
ekranında çözülmüş durumda ve kendi isteğiyle gönderiyor. Sunucu hâlâ kendi
başına hiçbir mesajı çözemiyor; yalnızca bir kullanıcının gönüllü olarak
ilettiği metni saklıyor. WhatsApp'ın şikâyet akışı da böyle çalışıyor.

Bu yüzden `mesaj_metni` alanına asla "kanıt" gözüyle bakılmamalı: gönderen
kişi metni değiştirmiş olabilir. Karar verirken yöneticinin elindeki asıl
bilgi, aynı mesaj için kaç ayrı kişinin şikâyette bulunduğu.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import ZamanDamgaliModel


class Sikayet(ZamanDamgaliModel):
    class Tur(models.TextChoices):
        FOTOGRAF = "fotograf", "Maç fotoğrafı"
        MESAJ = "mesaj", "Sohbet mesajı"

    class Sebep(models.TextChoices):
        MUSTEHCEN = "mustehcen", "Müstehcenlik veya çıplaklık"
        SIDDET = "siddet", "Şiddet veya tehdit"
        TACIZ = "taciz", "Hakaret, taciz veya nefret söylemi"
        SPAM = "spam", "Spam veya alakasız içerik"
        DIGER = "diger", "Diğer"

    class Durum(models.TextChoices):
        BEKLIYOR = "bekliyor", "İnceleniyor"
        KALDIRILDI = "kaldirildi", "İçerik kaldırıldı"
        REDDEDILDI = "reddedildi", "Kural ihlali bulunmadı"

    grup = models.ForeignKey(
        "groups.Grup",
        on_delete=models.CASCADE,
        related_name="sikayetler",
        verbose_name="grup",
    )
    bildiren = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="bildirdigi_icerikler",
        verbose_name="bildiren",
    )

    tur = models.CharField("tür", max_length=20, choices=Tur.choices)
    sebep = models.CharField("sebep", max_length=20, choices=Sebep.choices)
    aciklama = models.CharField("açıklama", max_length=500, blank=True)

    # İçeriğin kendisi silinse de şikâyet kaydı kalsın diye SET_NULL.
    fotograf = models.ForeignKey(
        "matches.MacFotografi",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sikayetler",
        verbose_name="fotoğraf",
    )
    mesaj = models.ForeignKey(
        "chat.Mesaj",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sikayetler",
        verbose_name="mesaj",
    )
    # Şikâyet edenin cihazında çözülmüş metin. Sunucu bunu kendisi üretemez.
    mesaj_metni = models.TextField("bildirilen metin", blank=True)

    durum = models.CharField(
        "durum", max_length=12, choices=Durum.choices,
        default=Durum.BEKLIYOR, db_index=True,
    )
    inceleyen = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inceledigi_sikayetler",
        verbose_name="inceleyen",
    )
    karar_tarihi = models.DateTimeField("karar tarihi", null=True, blank=True)
    karar_notu = models.CharField("karar notu", max_length=300, blank=True)

    class Meta:
        verbose_name = "şikâyet"
        verbose_name_plural = "şikâyetler"
        ordering = ["-olusturulma"]
        indexes = [models.Index(fields=["grup", "durum", "-olusturulma"])]
        constraints = [
            # Aynı kişi aynı fotoğrafı iki kez bildiremesin; sayaç şişerdi.
            models.UniqueConstraint(
                fields=["bildiren", "fotograf"],
                condition=models.Q(fotograf__isnull=False),
                name="fotograf_basina_tek_sikayet",
            ),
            models.UniqueConstraint(
                fields=["bildiren", "mesaj"],
                condition=models.Q(mesaj__isnull=False),
                name="mesaj_basina_tek_sikayet",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_tur_display()} · {self.get_sebep_display()}"

    @property
    def icerik_duruyor_mu(self) -> bool:
        """İçerik hâlâ yerinde mi? Kaldırılmışsa yöneticiye iş kalmıyor."""
        if self.tur == self.Tur.FOTOGRAF:
            return self.fotograf_id is not None
        return self.mesaj_id is not None and not self.mesaj.silindi
