"""
Web fontlarını (woff2) sunucu tarafı çizim için tek bir TTF'e dönüştürür.

Neden gerekiyor: dizilim görselini Pillow ile sunucuda çiziyoruz
(bkz. apps/matches/gorsel.py) ve Pillow woff2 okuyamıyor. Ayrıca sitedeki
fontlar Google Fonts'un "latin" ve "latin-ext" altkümeleri hâlinde; Türkçe
harfler ikiye bölünmüş durumda:

    latin      : ç Ç ö Ö ü Ü  (ama ğ Ğ İ ş Ş yok)
    latin-ext  : ğ Ğ ı İ ş Ş  (ama temel latin harfleri yok)

Yani ikisi de tek başına yetmiyor; birleştirilmeleri gerekiyor.

Bu betik yayına girmiyor, geliştirme sırasında bir kez çalıştırılıyor ve
ürettiği TTF'ler depoya konuyor. fonttools bu yüzden requirements.txt'te
yok; gerekirse:

    pip install "fonttools[woff]"
    python tools/font_birlestir.py
"""

from __future__ import annotations

import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
FONT_DIZINI = KOK / "static" / "fonts"

# (çıktı adı, [birleştirilecek altkümeler])
AILELER = [
    ("plex-sans.ttf", ["plex-sans-latin.woff2", "plex-sans-latin-ext.woff2"]),
    ("fraunces.ttf", ["fraunces-latin.woff2", "fraunces-latin-ext.woff2"]),
]

TURKCE = "çÇğĞıİöÖşŞüÜ"
TEMEL = "ABCXYZabcxyz0123456789 .-·"


def kapsam(font) -> set[int]:
    kod_noktalari: set[int] = set()
    for tablo in font["cmap"].tables:
        kod_noktalari |= set(tablo.cmap.keys())
    return kod_noktalari


def birlestir(cikti_adi: str, parcalar: list[str]) -> Path:
    from fontTools.merge import Merger
    from fontTools.ttLib import TTFont

    yollar = [str(FONT_DIZINI / p) for p in parcalar]
    for yol in yollar:
        if not Path(yol).exists():
            raise SystemExit(f"Font bulunamadı: {yol}")

    # Değişken font (fvar) birleştirilemiyor; önce sabit örneğe indiriliyor.
    gecici: list[str] = []
    for yol in yollar:
        font = TTFont(yol)
        if "fvar" in font:
            from fontTools.varLib.instancer import instantiateVariableFont

            eksenler = {
                eksen.axisTag: eksen.defaultValue for eksen in font["fvar"].axes
            }
            # Başlıklar için biraz daha kalın bir örnek daha okunaklı.
            if "wght" in eksenler:
                eksenler["wght"] = 600
            font = instantiateVariableFont(font, eksenler, inplace=True)
            hedef = FONT_DIZINI / f".gecici-{Path(yol).stem}.ttf"
            font.save(str(hedef))
            gecici.append(str(hedef))
        else:
            hedef = FONT_DIZINI / f".gecici-{Path(yol).stem}.ttf"
            font.save(str(hedef))
            gecici.append(str(hedef))

    birlesik = Merger().merge(gecici)
    cikti = FONT_DIZINI / cikti_adi
    birlesik.save(str(cikti))

    for yol in gecici:
        Path(yol).unlink(missing_ok=True)

    return cikti


def dogrula(yol: Path) -> None:
    from fontTools.ttLib import TTFont

    kod_noktalari = kapsam(TTFont(str(yol)))
    eksik = [h for h in TURKCE + TEMEL if ord(h) not in kod_noktalari]
    durum = "eksik: " + "".join(eksik) if eksik else "tam"
    print(f"  {yol.name}: {len(kod_noktalari)} glif, {durum}")
    if eksik:
        raise SystemExit(f"{yol.name} gerekli harfleri kapsamıyor.")


def main() -> int:
    print("Fontlar birleştiriliyor")
    for cikti_adi, parcalar in AILELER:
        cikti = birlestir(cikti_adi, parcalar)
        dogrula(cikti)
    print("Tamam.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
