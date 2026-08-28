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
        ICERIK_BILDIRILDI = "icerik_bildirildi", "İçerik bildirildi"

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
        r"""
        Şablonda kullanılan hedef. Dış bağlantılar sessizce yok sayılır.

        Yalnızca "/" ile başlamak yetmiyor:

          //baska.site   → protokole göreli adres; dışarı çıkar
          /\baska.site   → tarayıcılar ters bölüyü "/" gibi okuduğu için
                           yukarıdakiyle aynı kapıya çıkar
          satır sonu     → Location başlığına başlık enjeksiyonu

        Bugün hedef_url kullanıcıdan gelmiyor: bütün çağrı yerleri
        reverse() ile üretiyor. Yani sömürülebilir bir yol yok. Ama bu
        özellik kodda "açık yönlendirmeye karşı koruma" diye anılıyor ve
        okundu_isaretle() doğrudan buradan redirect ediyor; korumanın
        gerçekten koruması gerekiyor.
        """
        yol = self.hedef_url or ""
        if not yol.startswith("/"):
            return ""
        if yol.startswith("//") or yol.startswith("/\\"):
            return ""
        # Denetim karakteri (satır sonu, sekme, NUL, DEL) taşıyan adres geçmez.
        if any(karakter < " " or karakter == "\x7f" for karakter in yol):
            return ""
        return yol


def bildir(alici, tur: str, baslik: str, mesaj: str = "", hedef_url: str = "") -> Bildirim | None:
    """Tek bir kullanıcıya bildirim yazar. Kişinin kendi eylemi ise atlanır."""
    if alici is None or not getattr(alici, "pk", None):
        return None
    bildirim = Bildirim.objects.create(
        alici=alici,
        tur=tur,
        baslik=baslik[:120],
        mesaj=mesaj[:250],
        hedef_url=hedef_url[:250] if hedef_url.startswith("/") else "",
    )
    _telefona_it([bildirim])
    return bildirim


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
    _telefona_it(kayitlar)
    return len(kayitlar)


def _telefona_it(bildirimler) -> None:
    """
    Bildirimleri cihazlara iter. Hata olursa yutuluyor.

    Push bir KOLAYLIK, tek kanal değil: bildirim zaten veritabanına yazıldı
    ve uygulama içinde görünüyor. Gönderim başarısız diye bildirim yazma
    işlemi başarısız sayılmamalı, o yüzden buradan hiçbir istisna yukarı
    çıkmıyor.
    """
    try:
        from .push import bildirimleri_it, push_acik_mi

        if push_acik_mi():
            bildirimleri_it(bildirimler)
    except Exception:  # pragma: no cover - savunma amaçlı
        import logging

        logging.getLogger(__name__).exception("Push gönderimi başarısız")


class PushAbonelik(models.Model):
    """
    Bir cihazın Web Push aboneliği.

    Uygulamanın bildirim sistemi eksiksizdi ama tamamen çekmeliydi: kişi
    maçın 21:30'a alındığını ancak uygulamayı bir dahaki açışında görüyordu,
    ki bu çoğu insan için zaten arabaya bindiği an. Android kabuğu
    bildirimler açık üretilmişti; eksik olan tek şey web tarafının izin
    isteyip abone olmasıydı.

    Bir kullanıcının birden çok cihazı olabilir; her cihaz ayrı satır.
    `endpoint` tarayıcının verdiği adres ve doğal anahtar görevi görüyor.

    ⚠️ İÇERİK TAŞIMIYOR. Sohbet uçtan uca şifreli; sunucu mesajı okuyamıyor,
    dolayısıyla bildirime koyamıyor da. Sohbet bildirimi yalnızca "yeni mesaj
    var" diyor. Maç, yoklama ve iptal bildirimleri metin taşıyabiliyor çünkü
    o metni zaten sunucu yazıyor.
    """

    kullanici = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_abonelikleri",
        verbose_name="kullanıcı",
    )
    endpoint = models.TextField("uç adres", unique=True)
    # Tarayıcının ürettiği şifreleme anahtarları; içerik bunlarla şifreleniyor.
    p256dh = models.CharField("p256dh", max_length=255)
    auth = models.CharField("auth", max_length=255)
    # Hangi tarayıcı/cihaz olduğunu ayırt etmek için; kullanıcıya gösterilmiyor.
    tarayici = models.CharField("tarayıcı", max_length=200, blank=True)
    olusturulma = models.DateTimeField("eklenme", auto_now_add=True)
    son_kullanim = models.DateTimeField("son başarılı gönderim", null=True, blank=True)

    class Meta:
        verbose_name = "push aboneliği"
        verbose_name_plural = "push abonelikleri"
        ordering = ["-olusturulma"]
        indexes = [models.Index(fields=["kullanici"])]

    def __str__(self) -> str:
        return f"{self.kullanici} · {self.endpoint[:40]}…"
