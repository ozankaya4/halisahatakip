"""
Ham ekran görüntülerini Play Store'un istediği ölçülere getirir.

Play'in kuralı: kenarlar 320-3840 piksel arası, en boy oranı 16:9 ya da 9:16,
PNG veya JPEG, en fazla 8 MB. Telefondan ya da tarayıcıdan alınan görüntüler
neredeyse hiçbir zaman tam 9:16 çıkmıyor.

Görüntü ASLA gerilmiyor. Oranı korunarak hedefin içine sığdırılıyor, artan yer
görüntünün KENDİ arka plan rengiyle dolduruluyor: renk kenar piksellerinden
okunduğu için koyu temada koyu, açık temada açık dolgu çıkıyor ve ekleme
görünmüyor.

Kullanım:

    1. Ham görüntüleri deploy/play/ham/ klasörüne koyun
    2. python tools/play_ekran_goruntusu.py
    3. Çıktılar deploy/play/telefon/ klasöründe

Tablet ölçüleri için:

    python tools/play_ekran_goruntusu.py tablet-7
    python tools/play_ekran_goruntusu.py tablet-10
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from PIL import Image

KOK = Path(__file__).resolve().parent.parent
HAM_DIZIN = KOK / "deploy" / "play" / "ham"

# Play Store telefon bölümü 16:9 ya da 9:16 istiyor; 1080x1920 tam 9:16.
# Tablet bölümleri daha esnek, oradaki ölçüler yaygın tablet çözünürlükleri.
HEDEFLER = {
    "telefon": (1080, 1920),
    "tablet-7": (1200, 1920),
    "tablet-10": (1600, 2560),
}

AZAMI_BAYT = 8 * 1024 * 1024
UZANTILAR = {".png", ".jpg", ".jpeg", ".webp"}


def kenar_rengi(gorsel: Image.Image) -> tuple[int, int, int]:
    """
    Görüntünün kenarlarında en çok geçen renk.

    Dolgu rengi buradan geliyor; sabit bir renk yazsaydık açık temada alınmış
    bir görüntünün etrafında koyu şeritler oluşurdu.
    """
    genislik, yukseklik = gorsel.size
    pikseller: list[tuple[int, int, int]] = []

    # Dört kenardan örnek; her pikseli okumaya gerek yok.
    adim = max(1, genislik // 200)
    for x in range(0, genislik, adim):
        pikseller.append(gorsel.getpixel((x, 0)))
        pikseller.append(gorsel.getpixel((x, yukseklik - 1)))

    adim = max(1, yukseklik // 200)
    for y in range(0, yukseklik, adim):
        pikseller.append(gorsel.getpixel((0, y)))
        pikseller.append(gorsel.getpixel((genislik - 1, y)))

    return Counter(pikseller).most_common(1)[0][0]


def donustur(kaynak: Path, hedef_boyut: tuple[int, int], cikti_dizin: Path) -> Path:
    hedef_g, hedef_y = hedef_boyut

    gorsel = Image.open(kaynak)
    # Play saydamlık kabul etmiyor; alfa kanalı burada düşüyor.
    if gorsel.mode != "RGB":
        gorsel = gorsel.convert("RGB")

    dolgu = kenar_rengi(gorsel)

    # Oranı bozmadan hedefin içine sığdır.
    olcek = min(hedef_g / gorsel.width, hedef_y / gorsel.height)
    yeni = (max(1, round(gorsel.width * olcek)), max(1, round(gorsel.height * olcek)))
    gorsel = gorsel.resize(yeni, Image.LANCZOS)

    tuval = Image.new("RGB", hedef_boyut, dolgu)
    tuval.paste(gorsel, ((hedef_g - yeni[0]) // 2, (hedef_y - yeni[1]) // 2))

    cikti_dizin.mkdir(parents=True, exist_ok=True)
    hedef = cikti_dizin / f"{kaynak.stem}.png"
    tuval.save(hedef, format="PNG", optimize=True)

    # 8 MB sınırını aşarsa JPEG'e düşülüyor; ekran görüntüsünde fark edilmez.
    if hedef.stat().st_size > AZAMI_BAYT:
        hedef.unlink()
        hedef = cikti_dizin / f"{kaynak.stem}.jpg"
        tuval.save(hedef, format="JPEG", quality=90, optimize=True)

    return hedef


def main() -> int:
    ad = sys.argv[1] if len(sys.argv) > 1 else "telefon"
    if ad not in HEDEFLER:
        print(f"Bilinmeyen hedef: {ad}. Seçenekler: {', '.join(HEDEFLER)}")
        return 1

    if not HAM_DIZIN.exists():
        HAM_DIZIN.mkdir(parents=True, exist_ok=True)
        print(f"Ham görüntüleri şu klasöre koyun ve tekrar çalıştırın:\n  {HAM_DIZIN}")
        return 1

    kaynaklar = sorted(
        y for y in HAM_DIZIN.iterdir() if y.suffix.lower() in UZANTILAR
    )
    if not kaynaklar:
        print(f"{HAM_DIZIN} boş.")
        return 1

    cikti_dizin = KOK / "deploy" / "play" / ad
    boyut = HEDEFLER[ad]
    print(f"{ad}: {boyut[0]}x{boyut[1]}")

    for kaynak in kaynaklar:
        onceki = Image.open(kaynak).size
        hedef = donustur(kaynak, boyut, cikti_dizin)
        kb = hedef.stat().st_size // 1024
        print(f"  {kaynak.name}  {onceki[0]}x{onceki[1]} -> {hedef.name}  ({kb} KB)")

    print(f"\nÇıktılar: {cikti_dizin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
