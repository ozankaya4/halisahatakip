"""
PWA ikonlarını üretir.

    .venv\\Scripts\\python.exe tools\\ikon_uret.py

Tasarım static/img/favicon.svg ile aynı: koyu yeşil zemin üzerinde saha
çizgileri. İkonlar depoya işleniyor, bu betik yalnızca yeniden üretmek
gerektiğinde çalıştırılıyor (renk değişikliği, boyut ekleme vb.).

"maskable" ikon ayrı üretiliyor: Android ikonu daireye/kareye kırpabildiği
için çizim, kenarlardan %20 boşluk bırakılan "güvenli alan"ın içinde kalıyor.
Normal ikonda bu boşluk olmasa daha dolgun görünüyor, maskable'da ise
kırpılınca saha çizgileri kesiliyordu.
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

KOK = pathlib.Path(__file__).resolve().parent.parent
HEDEF = KOK / "static" / "img"

ZEMIN = (31, 77, 56, 255)      # #1f4d38  mürekkep yeşili
CIZGI = (246, 243, 234, 255)   # #f6f3ea  kâğıt beyazı


def ikon_ciz(boyut: int, guvenli_oran: float, kose_orani: float) -> Image.Image:
    """
    Tek bir ikon üretir.

    guvenli_oran: çizimin kenarlardan bırakacağı boşluk (0.0-0.4).
    kose_orani  : köşe yuvarlaklığı (0 = kare, 0.5 = daire).
    """
    # 4 kat büyük çizip küçültüyoruz: kenarlar yumuşak çıksın.
    olcek = 4
    b = boyut * olcek
    gorsel = Image.new("RGBA", (b, b), (0, 0, 0, 0))
    firca = ImageDraw.Draw(gorsel)

    firca.rounded_rectangle([0, 0, b - 1, b - 1], radius=int(b * kose_orani), fill=ZEMIN)

    pay = int(b * guvenli_oran)
    saha = [pay, int(pay * 1.35), b - pay, b - int(pay * 1.35)]
    kalinlik = max(2, int(b * 0.035))

    firca.rounded_rectangle(saha, radius=int(b * 0.02), outline=CIZGI, width=kalinlik)

    # Orta saha çizgisi
    orta_x = b // 2
    firca.line([orta_x, saha[1], orta_x, saha[3]], fill=CIZGI, width=kalinlik)

    # Orta daire
    yaricap = int((saha[3] - saha[1]) * 0.22)
    merkez_y = (saha[1] + saha[3]) // 2
    firca.ellipse(
        [orta_x - yaricap, merkez_y - yaricap, orta_x + yaricap, merkez_y + yaricap],
        outline=CIZGI,
        width=kalinlik,
    )

    return gorsel.resize((boyut, boyut), Image.Resampling.LANCZOS)


def main() -> None:
    HEDEF.mkdir(parents=True, exist_ok=True)

    uretilecek = [
        # (dosya adı, boyut, güvenli oran, köşe oranı)
        ("ikon-192.png", 192, 0.16, 0.16),
        ("ikon-512.png", 512, 0.16, 0.16),
        # Maskable: kırpılmaya karşı geniş boşluk, köşe yuvarlatma yok
        # (maskeyi işletim sistemi uyguluyor).
        ("ikon-maskable-192.png", 192, 0.26, 0.0),
        ("ikon-maskable-512.png", 512, 0.26, 0.0),
        # iOS ana ekran ikonu: maske uygulanmıyor, köşeleri iOS yuvarlıyor.
        ("apple-touch-icon.png", 180, 0.16, 0.0),
    ]

    for ad, boyut, guvenli, kose in uretilecek:
        yol = HEDEF / ad
        ikon_ciz(boyut, guvenli, kose).save(yol, format="PNG", optimize=True)
        print(f"  {ad:28} {boyut}x{boyut}  {yol.stat().st_size:>6} bayt")


if __name__ == "__main__":
    main()
