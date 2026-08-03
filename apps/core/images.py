"""
Güvenli görsel yükleme hattı.

Kullanıcıdan gelen hiçbir dosya olduğu gibi diske yazılmaz. Her görsel
doğrulanır, çözülür ve **yeniden kodlanır**. Bu sayede:

* Polyglot dosyalar (aynı anda hem geçerli GIF hem çalıştırılabilir PHP/HTML
  olan dosyalar) yeniden kodlama sırasında yok olur.
* EXIF verisi — özellikle telefonların gömdüğü GPS koordinatları — tamamen
  silinir. Halı saha fotoğrafları üzerinden ev/işyeri konumu sızmasın diye
  bu adım isteğe bağlı değildir.
* Dekompresyon bombaları (küçük dosya, devasa piksel sayısı) çözülmeden önce
  piksel sayısı sınırıyla reddedilir.
* Dosya adı kullanıcıdan hiç alınmaz; UUID üretilir. Yol geçişi (../) ve
  çift uzantı (resim.jpg.php) saldırıları böylece anlamsızlaşır.

SVG bilinçli olarak desteklenmez: içinde <script> taşıyabildiği için
güvenilmeyen kaynaktan gelen SVG doğrudan bir XSS aracıdır.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

# Pillow'un kendi bomba koruması. Kenar sınırımızın karesinden biraz yüksek
# tutuyoruz; asıl reddi biz aşağıda daha net bir mesajla yapıyoruz.
Image.MAX_IMAGE_PIXELS = (settings.MAX_IMAGE_DIMENSION**2) * 2

# Pillow'un *çözebildiği* biçimlerden yalnızca bu dördünü kabul ediyoruz.
IZINLI_BICIMLER = {"JPEG", "PNG", "WEBP", "GIF"}
IZINLI_UZANTILAR = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Erken (ucuz) eleme için; güvenlik kararı buna dayanmaz, asıl kontrol Pillow'dur.
IZINLI_ICERIK_TIPLERI = {
    "image/jpeg",
    "image/pjpeg",
    "image/png",
    "image/webp",
    "image/gif",
}


@dataclass(frozen=True)
class GorselProfili:
    """Bir yükleme türü için hedef boyut ve kalite."""

    ad: str
    en_buyuk_kenar: int
    kalite: int


AVATAR = GorselProfili(ad="avatar", en_buyuk_kenar=512, kalite=82)
MAC_FOTOGRAFI = GorselProfili(ad="mac", en_buyuk_kenar=1920, kalite=80)


def _uzanti(dosya_adi: str) -> str:
    ad = (dosya_adi or "").lower()
    nokta = ad.rfind(".")
    return ad[nokta:] if nokta != -1 else ""


def gorseli_dogrula(yuklenen) -> None:
    """
    Diske yazmadan önceki hızlı elemeler.

    ModelForm alan doğrulaması olarak da kullanılabilsin diye ValidationError
    fırlatır.
    """
    if yuklenen is None:
        raise ValidationError("Dosya bulunamadı.")

    boyut = getattr(yuklenen, "size", None)
    if boyut is None:
        raise ValidationError("Dosya boyutu okunamadı.")
    if boyut == 0:
        raise ValidationError("Dosya boş görünüyor.")
    if boyut > settings.MAX_UPLOAD_SIZE:
        mb = settings.MAX_UPLOAD_SIZE // (1024 * 1024)
        raise ValidationError(f"Dosya çok büyük. En fazla {mb} MB yükleyebilirsiniz.")

    if _uzanti(getattr(yuklenen, "name", "")) not in IZINLI_UZANTILAR:
        raise ValidationError(
            "Yalnızca JPG, PNG, WEBP ve GIF dosyaları yüklenebilir."
        )

    icerik_tipi = (getattr(yuklenen, "content_type", "") or "").lower().split(";")[0]
    if icerik_tipi and icerik_tipi not in IZINLI_ICERIK_TIPLERI:
        raise ValidationError("Bu dosya türü desteklenmiyor.")


def gorseli_isle(yuklenen, profil: GorselProfili) -> tuple[ContentFile, str]:
    """
    Yüklenen dosyayı doğrula, yeniden kodla ve kaydedilmeye hazır hâle getir.

    Dönen değer: (içerik, dosya_adi). Dosya adı her zaman rastgele bir UUID +
    ".webp" olur; kullanıcının verdiği ad hiçbir şekilde kullanılmaz.
    """
    gorseli_dogrula(yuklenen)

    ham = yuklenen.read()
    yuklenen.seek(0)

    # 1. adım: yapıyı doğrula. verify() çağrısı dosyayı "tüketir", bu yüzden
    # ayrı bir tampon üzerinde çalışılır ve sonrasında yeniden açılır.
    try:
        with Image.open(io.BytesIO(ham)) as sonda:
            sonda.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise ValidationError(
            "Dosya geçerli bir görsel değil ya da bozuk. Lütfen başka bir dosya deneyin."
        )

    # 2. adım: gerçekten çöz ve içeriği kontrol et.
    try:
        with Image.open(io.BytesIO(ham)) as gorsel:
            bicim = (gorsel.format or "").upper()
            if bicim not in IZINLI_BICIMLER:
                raise ValidationError("Bu görsel biçimi desteklenmiyor.")

            en, boy = gorsel.size
            if en <= 0 or boy <= 0:
                raise ValidationError("Görsel boyutları okunamadı.")
            if en > settings.MAX_IMAGE_DIMENSION or boy > settings.MAX_IMAGE_DIMENSION:
                raise ValidationError(
                    f"Görsel çözünürlüğü çok yüksek "
                    f"(en fazla {settings.MAX_IMAGE_DIMENSION}x{settings.MAX_IMAGE_DIMENSION} piksel)."
                )

            # Animasyonlu dosyalarda yalnızca ilk kare alınır.
            if getattr(gorsel, "n_frames", 1) > 1:
                gorsel.seek(0)

            # EXIF yönlendirmesini piksellere uygula, sonra veriyi at.
            gorsel = ImageOps.exif_transpose(gorsel)

            # Alfa kanalını beyaz zemine düzleştir (WEBP'de saydamlık korunabilir
            # ama profil/maç görselleri için düz zemin daha öngörülebilir).
            if gorsel.mode in ("RGBA", "LA", "P", "PA"):
                gorsel = gorsel.convert("RGBA")
                zemin = Image.new("RGBA", gorsel.size, (255, 255, 255, 255))
                zemin.alpha_composite(gorsel)
                gorsel = zemin.convert("RGB")
            elif gorsel.mode != "RGB":
                gorsel = gorsel.convert("RGB")

            gorsel.thumbnail(
                (profil.en_buyuk_kenar, profil.en_buyuk_kenar),
                Image.Resampling.LANCZOS,
            )

            # Yeni bir görsel nesnesine kopyalayarak taşınan tüm meta veriyi
            # (EXIF, ICC, XMP, yorum blokları) geride bırakıyoruz.
            temiz = Image.new("RGB", gorsel.size)
            temiz.paste(gorsel)

            cikti = io.BytesIO()
            temiz.save(cikti, format="WEBP", quality=profil.kalite, method=4)
    except ValidationError:
        raise
    except Image.DecompressionBombError:
        raise ValidationError("Görsel güvenlik sınırlarının dışında; reddedildi.")
    except (OSError, ValueError) as hata:
        raise ValidationError(f"Görsel işlenemedi: {hata}")

    cikti.seek(0)
    dosya_adi = f"{uuid.uuid4().hex}.webp"
    return ContentFile(cikti.read(), name=dosya_adi), dosya_adi
