"""
Play Store "öne çıkan görsel" (feature graphic) üretir: 1024x500 PNG.

Play Console'un zorunlu tuttuğu tek görsel bu; uygulama simgesi zaten
static/img/ikon-512.png olarak var.

Tasarım, uygulamanın dizilim görseliyle (apps/matches/gorsel.py) aynı
dünyadan: aynı çim yeşili, aynı fontlar, aynı oyuncu diskleri. Mağazada
görülen ilk şeyin uygulamanın içindekiyle aynı görünmesi amaçlanıyor.

Çalıştırma:

    .venv\\Scripts\\python.exe tools/play_gorseli_uret.py

Çıktı: deploy/play/one-cikan-1024x500.png
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

KOK = Path(__file__).resolve().parent.parent
FONT_DIZINI = KOK / "static" / "fonts"
CIKTI_DIZINI = KOK / "deploy" / "play"

GENISLIK, YUKSEKLIK = 1024, 500

# Renkler dizilim görseliyle birebir aynı.
YESIL = (31, 77, 56)
YESIL_KOYU = (24, 60, 44)
CIZGI = (255, 255, 255, 40)
KAGIT = (242, 239, 230)
SOLGUN = (183, 205, 190)
HARDAL = (226, 185, 59)
KOYU_FORMA = (28, 30, 26)

# Play Store görseli bazı yerleşimlerde kenarlardan kırpılabiliyor;
# önemli hiçbir şey bu payın dışına taşmıyor.
GUVENLI_PAY = 64


def font(ad: str, boyut: int):
    yol = FONT_DIZINI / ad
    if not yol.exists():
        raise SystemExit(
            f"Font bulunamadı: {yol}\n"
            "Önce 'python tools/font_birlestir.py' çalıştırın."
        )
    return ImageFont.truetype(str(yol), boyut)


def metin_genisligi(ciz, metin, yazi_tipi) -> int:
    sol, _, sag, _ = ciz.textbbox((0, 0), metin, font=yazi_tipi)
    return sag - sol


def cim_ciz(gorsel: Image.Image) -> None:
    """Biçilmiş çim şeritleri."""
    ciz = ImageDraw.Draw(gorsel, "RGBA")
    serit = 12
    adim = GENISLIK / serit
    for i in range(serit):
        if i % 2:
            ciz.rectangle(
                (round(i * adim), 0, round((i + 1) * adim), YUKSEKLIK),
                fill=YESIL_KOYU,
            )


def saha_cizgileri_ciz(gorsel: Image.Image) -> None:
    """
    Sağ kenardan taşan orta yuvarlak ve dikey çizgi.

    Tam saha çizmek 1024x500'de kalabalık duruyor; sahanın bir parçasının
    kadraja girmesi hem futbolu anlatıyor hem metne yer bırakıyor.
    """
    ciz = ImageDraw.Draw(gorsel, "RGBA")
    kalinlik = 3

    merkez_x, merkez_y = 790, YUKSEKLIK // 2
    yaricap = 118
    ciz.ellipse(
        (merkez_x - yaricap, merkez_y - yaricap, merkez_x + yaricap, merkez_y + yaricap),
        outline=CIZGI,
        width=kalinlik,
    )
    ciz.line((merkez_x, 0, merkez_x, YUKSEKLIK), fill=CIZGI, width=kalinlik)


def oyuncu_diski(gorsel, ciz, merkez, yaricap, koyu: bool, harfler: str,
                 puan: str | None = None, yildiz: bool = False) -> None:
    mx, my = merkez
    dolgu = KOYU_FORMA if koyu else KAGIT
    yazi = KAGIT if koyu else (27, 28, 23)

    ciz.ellipse(
        (mx - yaricap - 3, my - yaricap - 3, mx + yaricap + 3, my + yaricap + 3),
        fill=(0, 0, 0, 70),
    )
    ciz.ellipse((mx - yaricap, my - yaricap, mx + yaricap, my + yaricap), fill=dolgu)

    harf_font = font("plex-sans.ttf", round(yaricap * 0.86))
    _, ust, _, alt = ciz.textbbox((0, 0), harfler, font=harf_font)
    ciz.text(
        (mx - metin_genisligi(ciz, harfler, harf_font) / 2, my - (alt - ust) / 2 - ust),
        harfler,
        font=harf_font,
        fill=yazi,
    )

    if puan:
        rozet_font = font("plex-sans.ttf", 22)
        genislik = metin_genisligi(ciz, puan, rozet_font) + 18
        yuk = 30
        rx, ry = mx + yaricap - 6, my - yaricap + 2
        ciz.rounded_rectangle(
            (rx - genislik / 2, ry - yuk / 2, rx + genislik / 2, ry + yuk / 2),
            radius=yuk / 2,
            fill=(47, 143, 78),
            outline=(255, 255, 255, 170),
            width=2,
        )
        _, ust, _, alt = ciz.textbbox((0, 0), puan, font=rozet_font)
        ciz.text(
            (rx - metin_genisligi(ciz, puan, rozet_font) / 2, ry - (alt - ust) / 2 - ust),
            puan,
            font=rozet_font,
            fill=KAGIT,
        )

    if yildiz:
        # Yıldız diskin dışına taşıyor; içeride kalınca sarı bir lekeye
        # dönüşüyor ve maçın adamı işareti olduğu anlaşılmıyor.
        yildiz_ciz(ciz, mx - yaricap + 2, my + yaricap - 2, yaricap * 0.42, HARDAL)


def yildiz_ciz(ciz, mx, my, dis, renk) -> None:
    ic = dis * 0.42
    noktalar = []
    for i in range(10):
        r = dis if i % 2 == 0 else ic
        aci = -math.pi / 2 + i * math.pi / 5
        noktalar.append((mx + r * math.cos(aci), my + r * math.sin(aci)))
    ciz.polygon(noktalar, fill=renk, outline=(24, 30, 26))


def dizilim_ciz(gorsel, ciz) -> None:
    """Sağ tarafta küçük bir dizilim: uygulamanın imza ekranı."""
    yaricap = 40
    # (x, y, koyu, baş harfler, puan, yıldız)
    #
    # Açık formalılar orta çizginin solunda, koyular sağında: küçük de olsa
    # iki takımın karşı karşıya durduğu okunuyor. Hiçbir disk sağ kenara
    # GUVENLI_PAY'den fazla yaklaşmıyor.
    oyuncular = [
        (628, 138, False, "ÇY", None, False),
        (628, 362, False, "MÖ", None, False),
        (712, 250, False, "OK", "8.4", True),
        (874, 168, True, "İG", None, False),
        (874, 332, True, "BŞ", None, False),
    ]
    for x, y, koyu, harf, puan, yildiz in oyuncular:
        oyuncu_diski(gorsel, ciz, (x, y), yaricap, koyu, harf, puan, yildiz)


def metin_ciz(gorsel, ciz) -> None:
    sol = GUVENLI_PAY

    baslik_font = font("fraunces.ttf", 74)
    alt_font = font("plex-sans.ttf", 27)
    etiket_font = font("plex-sans.ttf", 21)

    # Üst etiket
    etiket = "HALI SAHA GRUPLARI İÇİN"
    ciz.text((sol, 118), etiket, font=etiket_font, fill=SOLGUN)

    # Başlık iki satır: tek satırda 74 punto sığmıyor, küçültmek yerine
    # bölmek daha okunaklı duruyor.
    ciz.text((sol, 158), "Halısaha", font=baslik_font, fill=KAGIT)
    ciz.text((sol, 238), "Defteri", font=baslik_font, fill=KAGIT)

    # İnce ayraç
    ciz.line((sol, 336, sol + 96, 336), fill=(255, 255, 255, 110), width=3)

    ciz.text((sol, 356), "Maç, kadro, dizilim ve puan.", font=alt_font, fill=SOLGUN)


def main() -> int:
    CIKTI_DIZINI.mkdir(parents=True, exist_ok=True)

    gorsel = Image.new("RGB", (GENISLIK, YUKSEKLIK), YESIL)
    cim_ciz(gorsel)
    saha_cizgileri_ciz(gorsel)

    ciz = ImageDraw.Draw(gorsel, "RGBA")
    dizilim_ciz(gorsel, ciz)
    metin_ciz(gorsel, ciz)

    hedef = CIKTI_DIZINI / "one-cikan-1024x500.png"
    # Play Store saydamlık kabul etmiyor; RGB olarak kaydediliyor.
    gorsel.save(hedef, format="PNG", optimize=True)
    print(f"{hedef}  ({hedef.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
