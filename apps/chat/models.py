"""
Uçtan uca şifreli grup sohbeti — sunucu tarafı modeller.

TASARIM ÖZETİ
-------------
Sunucu hiçbir mesajın içeriğini okuyamaz. Elindeki her şey şifreli bloblardan
ibarettir:

1. Her kullanıcının bir RSA-OAEP anahtar çifti vardır. Açık anahtar sunucuda
   düz metin olarak durur (zaten açıktır). Özel anahtar tarayıcıda üretilir,
   kullanıcının **şifreleme parolasından** PBKDF2 ile türetilen bir anahtarla
   AES-GCM ile şifrelenir ve sunucuya yalnızca şifreli hâlde gönderilir.
   Şifreleme parolası hiçbir zaman sunucuya ulaşmaz.

2. Her grubun sürümlenmiş bir AES-256-GCM sohbet anahtarı vardır. Bu anahtar
   her üye için o üyenin açık anahtarıyla ayrı ayrı sarmalanır (AnahtarPaketi).
   Sunucu sarmalanmış blobları saklar; açamaz.

3. Mesajlar tarayıcıda grup anahtarıyla AES-GCM ile şifrelenir. Sunucuya
   yalnızca şifreli metin, IV ve anahtar sürümü gider.

BİLİNÇLİ SINIRLAR (kullanıcıya README'de de açıkça yazılmıştır)
---------------------------------------------------------------
* Şifreleme parolası unutulursa mesaj geçmişi **kurtarılamaz**. Sunucuda
  parolayı ya da özel anahtarı çözecek hiçbir bilgi yoktur.
* Gruba yeni katılan biri, katılmadan önceki mesajları okuyamaz (o sürümün
  anahtarı kendisi için hiç sarmalanmamıştır).
* Nihai yönetici dâhil hiç kimse sunucu üzerinden mesaj okuyamaz.
* Grup anahtarını bilen bir üye, teknik olarak başka bir üyenin adına mesaj
  şifreleyebilir. Buna karşı mesaj başına imza gerekir; bu sürümde yoktur.
  Sunucunun göndereni değiştirmesi ise engellidir: gönderen kimliği AES-GCM
  ek doğrulanmış verisine (AAD) dâhil edilir.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import ZamanDamgaliModel

# Base64 kodlanmış şifreli mesaj için üst sınır (~6 KB düz metin).
MAX_SIFRELI_UZUNLUK = 8192


class AnahtarCifti(ZamanDamgaliModel):
    """Kullanıcının kimlik anahtar çifti. Özel anahtar yalnızca şifreli hâlde."""

    kullanici = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="anahtar_cifti",
        verbose_name="kullanıcı",
    )
    # RSA-OAEP açık anahtarı, JWK biçiminde. Gizli değildir.
    acik_anahtar = models.TextField("açık anahtar (JWK)")
    # PKCS#8 özel anahtarın AES-GCM ile şifrelenmiş hâli (base64).
    sifreli_ozel_anahtar = models.TextField("şifreli özel anahtar")
    # PBKDF2 parametreleri — parolanın kendisi asla saklanmaz.
    tuz = models.CharField("tuz (base64)", max_length=64)
    iv = models.CharField("IV (base64)", max_length=32)
    yineleme = models.PositiveIntegerField("PBKDF2 yineleme sayısı")
    # Açık anahtarın SHA-256 parmak izi; kullanıcılar birbirini doğrulayabilsin.
    parmak_izi = models.CharField("parmak izi", max_length=95, blank=True)

    class Meta:
        verbose_name = "anahtar çifti"
        verbose_name_plural = "anahtar çiftleri"

    def __str__(self) -> str:
        return f"{self.kullanici} anahtarı"


class AnahtarDegisimi(models.Model):
    """
    Bir kullanıcının kimlik anahtarını sıfırladığı an.

    NEDEN VAR: tarayıcı artık her üyenin açık anahtarını ilk gördüğü hâliyle
    hatırlıyor ve sonradan değişirse sarmalamayı reddediyor. Ama anahtarın
    değişmesi çoğu zaman saldırı değil: şifreleme parolasını unutan biri
    anahtarını sıfırlıyor ve yenisini üretiyor. Bu kayıt olmadan iki durum
    ekranda birbirinin aynısı görünüyordu.

    ⚠️ Bu bir KANIT DEĞİL, yalnızca gürültü azaltıcı. Veritabanına yazabilen
    biri buraya da sahte bir kayıt ekleyebilir. İşi, dürüst sıfırlamaların
    boşuna alarm vermesini önlemek; böylece gerçekten şüpheli olan uyarı
    dikkat çekiyor. Tek gerçek doğrulama, iki kişinin parmak izlerini
    yüz yüze karşılaştırması.
    """

    kullanici = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="anahtar_degisimleri",
        verbose_name="kullanıcı",
    )
    # Bırakılan anahtarın parmak izi. Yeni anahtarınki kaydedilmiyor: sıfırlama
    # anında henüz üretilmemiş oluyor.
    eski_parmak_izi = models.CharField("eski parmak izi", max_length=95, blank=True)
    olusturulma = models.DateTimeField("zaman", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "anahtar değişimi"
        verbose_name_plural = "anahtar değişimleri"
        ordering = ["-olusturulma"]
        indexes = [models.Index(fields=["kullanici", "-olusturulma"])]

    def __str__(self) -> str:
        return f"{self.kullanici} · {self.olusturulma:%d.%m.%Y %H:%M}"


class GrupAnahtari(ZamanDamgaliModel):
    """
    Bir grubun sürümlenmiş sohbet anahtarı.

    Anahtarın kendisi burada yoktur — yalnızca sürüm bilgisi. Anahtar
    materyali üye başına sarmalanmış olarak AnahtarPaketi'nde durur.
    """

    grup = models.ForeignKey(
        "groups.Grup",
        on_delete=models.CASCADE,
        related_name="sohbet_anahtarlari",
        verbose_name="grup",
    )
    surum = models.PositiveIntegerField("sürüm")
    olusturan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="olusturdugu_sohbet_anahtarlari",
        verbose_name="oluşturan",
    )
    aktif = models.BooleanField("aktif", default=True, db_index=True)
    # Üye ayrıldığında sunucu bunu işaretler; yeni sürüm üretilmesi gerekir.
    dondurulmeli = models.BooleanField("döndürülmeli", default=False)

    class Meta:
        verbose_name = "grup sohbet anahtarı"
        verbose_name_plural = "grup sohbet anahtarları"
        ordering = ["-surum"]
        constraints = [
            models.UniqueConstraint(fields=["grup", "surum"], name="benzersiz_anahtar_surumu")
        ]

    def __str__(self) -> str:
        return f"{self.grup} · sürüm {self.surum}"


class AnahtarPaketi(models.Model):
    """Grup anahtarının tek bir üyenin açık anahtarıyla sarmalanmış hâli."""

    grup_anahtari = models.ForeignKey(
        GrupAnahtari,
        on_delete=models.CASCADE,
        related_name="paketler",
        verbose_name="grup anahtarı",
    )
    uye = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="anahtar_paketleri",
        verbose_name="üye",
    )
    # RSA-OAEP ile sarmalanmış AES anahtarı (base64). Sunucu açamaz.
    sarmalanmis = models.TextField("sarmalanmış anahtar")
    olusturulma = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "anahtar paketi"
        verbose_name_plural = "anahtar paketleri"
        constraints = [
            models.UniqueConstraint(
                fields=["grup_anahtari", "uye"], name="uye_basina_tek_paket"
            )
        ]
        indexes = [models.Index(fields=["uye", "grup_anahtari"])]

    def __str__(self) -> str:
        return f"{self.uye} · {self.grup_anahtari}"


class Mesaj(models.Model):
    """
    Şifreli grup mesajı.

    `sifreli_metin` ve `iv` dışında içerik hakkında hiçbir bilgi tutulmaz.
    Sunucu meta veriyi (kim, ne zaman, hangi grup) görür — bu, sunucu tabanlı
    her sohbet sisteminde böyledir.
    """

    grup = models.ForeignKey(
        "groups.Grup", on_delete=models.CASCADE, related_name="mesajlar", verbose_name="grup"
    )
    gonderen = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gonderdigi_mesajlar",
        verbose_name="gönderen",
    )
    anahtar_surum = models.PositiveIntegerField("anahtar sürümü")
    sifreli_metin = models.TextField("şifreli metin")
    iv = models.CharField("IV (base64)", max_length=32)
    olusturulma = models.DateTimeField("gönderilme", auto_now_add=True, db_index=True)
    silindi = models.BooleanField("silindi", default=False)

    class Meta:
        verbose_name = "mesaj"
        verbose_name_plural = "mesajlar"
        ordering = ["olusturulma"]
        indexes = [models.Index(fields=["grup", "-olusturulma"])]

    def __str__(self) -> str:
        return f"{self.grup} · {self.gonderen} · {self.olusturulma:%d.%m.%Y %H:%M}"
