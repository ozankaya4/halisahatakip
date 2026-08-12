"""
Dizilimi paylaşılabilir bir görsele çizer.

Neden sunucuda çiziliyor: sayfanın ekran görüntüsünü tarayıcıda almak için
html2canvas gibi bir kütüphane gerekiyordu; hem içerik güvenlik politikamız
dışarıdan betik yüklemiyor (script-src 'self'), hem de o kütüphaneler modern
CSS'i (özel değişkenler, aspect-ratio, degrade) yanlış çiziyor. Pillow zaten
bağımlılıklarda ve konumları biz zaten yüzde olarak biliyoruz, dolayısıyla
sahayı doğrudan çizmek hem daha güvenilir hem her cihazda birebir aynı.

İki yön var:
  yatay  1920x1080 — WhatsApp, galeri, bilgisayar
  dikey  1080x1920 — Instagram/WhatsApp hikâyesi (tam ekran)

Dikeyde eksenler yer değiştiriyor: saklanan `x` (takımları ayıran eksen)
ekranda yukarıdan aşağıya, `y` soldan sağa çiziliyor. Sitedeki telefon
görünümüyle aynı kural (bkz. static/js/dizilim.js), böylece görsel de
telefonda gördüğüyle aynı yerleşimi gösteriyor.

Puanlar `dizilim_verisi()` çıktısından geliyor; puanlamasını tamamlamamış
kişi için görünüm katmanı orayı zaten temizliyor (`puanlari_gizle`), yani
görselde de puan çıkmıyor. Gizleme mantığı burada tekrar edilmiyor.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import timezone

# --- Ölçüler ---------------------------------------------------------------
YATAY = "yatay"
DIKEY = "dikey"
YONLER = (YATAY, DIKEY)

BOYUTLAR = {
    YATAY: (1920, 1080),
    DIKEY: (1080, 1920),
}

# --- Renkler (static/css/defter.css ile aynı) ------------------------------
KAGIT = (246, 243, 234)
KAGIT_UST = (255, 253, 247)
MUREKKEP = (27, 28, 23)
MUREKKEP_YUMUSAK = (85, 86, 75)
MUREKKEP_SOLUK = (139, 139, 125)
CETVEL = (214, 209, 192)
YESIL = (31, 77, 56)
YESIL_KOYU = (24, 60, 44)
YESIL_CIZGI = (255, 255, 255, 46)
HARDAL = (154, 117, 20)
BEYAZ = (255, 255, 255)

TAKIM_RENKLERI = {
    "a": (242, 239, 230),  # açık forma
    "b": (32, 34, 30),  # koyu forma
}
TAKIM_YAZI = {
    "a": (27, 28, 23),
    "b": (246, 243, 234),
}

PUAN_RENKLERI = {
    "puan-siyah": ((23, 25, 26), BEYAZ),
    "puan-kirmizi": ((192, 57, 43), BEYAZ),
    "puan-sari": ((226, 185, 59), (34, 28, 7)),
    "puan-yesil": ((47, 143, 78), BEYAZ),
    "puan-mavi": ((74, 163, 223), (16, 34, 46)),
    "puan-lacivert": ((31, 58, 147), BEYAZ),
    "puan-mor": ((111, 63, 168), BEYAZ),
}

FONT_DIZINI = Path(settings.BASE_DIR) / "static" / "fonts"


@lru_cache(maxsize=64)
def _font(ad: str, boyut: int):
    """
    Fontlar sayfa başına onlarca kez isteniyor; önbelleğe alınıyor.

    TTF'ler tools/font_birlestir.py ile üretiliyor: sitedeki woff2
    altkümeleri Türkçe harfleri ikiye bölüyor ve Pillow woff2 okumuyor.
    """
    from PIL import ImageFont

    yol = FONT_DIZINI / ad
    if not yol.exists():
        return ImageFont.load_default()
    return ImageFont.truetype(str(yol), boyut)


def baslik_fontu(boyut: int):
    return _font("fraunces.ttf", boyut)


def metin_fontu(boyut: int):
    return _font("plex-sans.ttf", boyut)


@dataclass(frozen=True)
class Yerlesim:
    """Bir yön için ölçüler. Tek yerde durunca iki düzen ayrışmıyor."""

    genislik: int
    yukseklik: int
    kenar: int
    baslik_yuksekligi: int
    ozet_yuksekligi: int
    alt_bilgi: int
    kart_yaricap: int
    ad_boyutu: int
    rozet_boyutu: int

    @property
    def saha_kutusu(self) -> tuple[int, int, int, int]:
        sol = self.kenar
        ust = self.kenar + self.baslik_yuksekligi
        sag = self.genislik - self.kenar
        alt = self.yukseklik - self.kenar - self.ozet_yuksekligi - self.alt_bilgi
        return sol, ust, sag, alt


def _yerlesim(yon: str) -> Yerlesim:
    genislik, yukseklik = BOYUTLAR[yon]
    if yon == YATAY:
        return Yerlesim(
            genislik=genislik,
            yukseklik=yukseklik,
            kenar=48,
            baslik_yuksekligi=132,
            ozet_yuksekligi=104,
            alt_bilgi=44,
            kart_yaricap=44,
            ad_boyutu=26,
            rozet_boyutu=25,
        )
    return Yerlesim(
        genislik=genislik,
        yukseklik=yukseklik,
        kenar=52,
        baslik_yuksekligi=268,
        ozet_yuksekligi=150,
        alt_bilgi=56,
        kart_yaricap=48,
        ad_boyutu=28,
        rozet_boyutu=27,
    )


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def _metin_genisligi(ciz, metin: str, font) -> int:
    sol, _, sag, _ = ciz.textbbox((0, 0), metin, font=font)
    return sag - sol


def _ortala(ciz, metin: str, font, merkez_x: int, y: int, renk) -> None:
    ciz.text((merkez_x - _metin_genisligi(ciz, metin, font) / 2, y), metin,
             font=font, fill=renk)


def _kisalt(ciz, metin: str, font, azami: int) -> str:
    """Sığmayan adı üç noktayla kısaltır."""
    if _metin_genisligi(ciz, metin, font) <= azami:
        return metin
    while metin and _metin_genisligi(ciz, metin + "…", font) > azami:
        metin = metin[:-1]
    return metin + "…"


def _ilk_ad(tam_ad: str) -> str:
    """
    Sahada yalnızca ilk ad; soyadıyla birlikte kartlar üst üste biniyor.

    Tek kelimelik adlar olduğu gibi kalıyor.
    """
    parcalar = tam_ad.split()
    if len(parcalar) <= 1:
        return tam_ad
    return parcalar[0]


def _avatar_diski(profil, capi: int):
    """Profil fotoğrafını daire olarak keser. Dosya okunamazsa None."""
    from PIL import Image, ImageDraw

    if not profil or not getattr(profil, "avatar", None):
        return None
    try:
        with profil.avatar.open("rb") as dosya:
            kaynak = Image.open(dosya)
            kaynak.load()
    except (OSError, ValueError):
        # Dosya silinmiş ya da bozuk; baş harflere düşülüyor.
        return None

    kaynak = kaynak.convert("RGBA")
    # Kısa kenardan kare kırpma, sonra ölçekleme.
    kisa = min(kaynak.size)
    sol = (kaynak.width - kisa) // 2
    ust = (kaynak.height - kisa) // 2
    kaynak = kaynak.crop((sol, ust, sol + kisa, ust + kisa))
    kaynak = kaynak.resize((capi, capi), Image.LANCZOS)

    maske = Image.new("L", (capi, capi), 0)
    ImageDraw.Draw(maske).ellipse((0, 0, capi - 1, capi - 1), fill=255)
    kaynak.putalpha(maske)
    return kaynak


# ---------------------------------------------------------------------------
# Saha
# ---------------------------------------------------------------------------
def _saha_ciz(gorsel, kutu: tuple[int, int, int, int], dikey: bool) -> None:
    """Çim, orta çizgi, orta yuvarlak ve ceza alanları."""
    from PIL import Image, ImageDraw

    sol, ust, sag, alt = kutu
    genislik, yukseklik = sag - sol, alt - ust

    saha = Image.new("RGB", (genislik, yukseklik), YESIL)
    ciz = ImageDraw.Draw(saha, "RGBA")

    # Biçilmiş çim şeritleri: uzun kenar boyunca.
    serit_sayisi = 10
    if dikey:
        adim = yukseklik / serit_sayisi
        for i in range(serit_sayisi):
            if i % 2:
                ciz.rectangle(
                    (0, round(i * adim), genislik, round((i + 1) * adim)),
                    fill=YESIL_KOYU,
                )
    else:
        adim = genislik / serit_sayisi
        for i in range(serit_sayisi):
            if i % 2:
                ciz.rectangle(
                    (round(i * adim), 0, round((i + 1) * adim), yukseklik),
                    fill=YESIL_KOYU,
                )

    kalinlik = max(2, round(min(genislik, yukseklik) / 320))
    kenar_bosluk = round(min(genislik, yukseklik) * 0.035)

    # Dış çizgi
    ciz.rectangle(
        (kenar_bosluk, kenar_bosluk, genislik - kenar_bosluk, yukseklik - kenar_bosluk),
        outline=YESIL_CIZGI,
        width=kalinlik,
    )

    orta_x, orta_y = genislik / 2, yukseklik / 2
    yuvarlak = round(min(genislik, yukseklik) * 0.13)
    ciz.ellipse(
        (orta_x - yuvarlak, orta_y - yuvarlak, orta_x + yuvarlak, orta_y + yuvarlak),
        outline=YESIL_CIZGI,
        width=kalinlik,
    )
    ciz.ellipse(
        (orta_x - kalinlik * 2, orta_y - kalinlik * 2,
         orta_x + kalinlik * 2, orta_y + kalinlik * 2),
        fill=YESIL_CIZGI,
    )

    if dikey:
        ciz.line((kenar_bosluk, orta_y, genislik - kenar_bosluk, orta_y),
                 fill=YESIL_CIZGI, width=kalinlik)
        alan_g = round(genislik * 0.44)
        alan_y = round(yukseklik * 0.14)
        for taraf in (0, 1):
            y0 = kenar_bosluk if taraf == 0 else yukseklik - kenar_bosluk - alan_y
            ciz.rectangle(
                ((genislik - alan_g) / 2, y0, (genislik + alan_g) / 2, y0 + alan_y),
                outline=YESIL_CIZGI,
                width=kalinlik,
            )
    else:
        ciz.line((orta_x, kenar_bosluk, orta_x, yukseklik - kenar_bosluk),
                 fill=YESIL_CIZGI, width=kalinlik)
        alan_g = round(genislik * 0.14)
        alan_y = round(yukseklik * 0.44)
        for taraf in (0, 1):
            x0 = kenar_bosluk if taraf == 0 else genislik - kenar_bosluk - alan_g
            ciz.rectangle(
                (x0, (yukseklik - alan_y) / 2, x0 + alan_g, (yukseklik + alan_y) / 2),
                outline=YESIL_CIZGI,
                width=kalinlik,
            )

    gorsel.paste(saha, (sol, ust))


KART_RENKLERI = {
    "sari": ((226, 192, 68), None),
    "kirmizi": ((192, 57, 43), None),
    # İkinci sarıdan kırmızı: köşeden bölünmüş kart, sitedeki gibi.
    "ikinci-sari": ((226, 192, 68), (192, 57, 43)),
}


def _yildiz_ciz(ciz, merkez_x, merkez_y, dis_yaricap, renk) -> None:
    """
    Beş köşeli yıldızı çokgen olarak çizer.

    Metin olarak yazılmıyor: ★ (U+2605) birleştirilmiş fontlarda yok ve
    yerine boş kutu çiziliyordu.
    """
    import math

    ic_yaricap = dis_yaricap * 0.42
    noktalar = []
    for i in range(10):
        yaricap = dis_yaricap if i % 2 == 0 else ic_yaricap
        aci = -math.pi / 2 + i * math.pi / 5
        noktalar.append(
            (merkez_x + yaricap * math.cos(aci), merkez_y + yaricap * math.sin(aci))
        )
    ciz.polygon(noktalar, fill=renk, outline=(24, 30, 26))


def _kart_ciz(ciz, sol, ust, genislik, yukseklik, tur: str) -> None:
    """Sarı / kırmızı / ikinci sarıdan kırmızı kart dikdörtgeni."""
    birinci, ikinci = KART_RENKLERI[tur]
    ciz.rectangle((sol, ust, sol + genislik, ust + yukseklik), fill=birinci)
    if ikinci:
        # Köşegen bölünme: sol üst sarı, sağ alt kırmızı.
        ciz.polygon(
            [(sol + genislik, ust), (sol + genislik, ust + yukseklik),
             (sol, ust + yukseklik)],
            fill=ikinci,
        )
    ciz.rectangle((sol, ust, sol + genislik, ust + yukseklik),
                  outline=(16, 20, 18), width=2)


def _top_ciz(ciz, merkez_x, merkez_y, yaricap) -> None:
    """Futbol topu: beyaz küre, üstünde koyu beşgen lekeler."""
    import math

    ciz.ellipse(
        (merkez_x - yaricap, merkez_y - yaricap, merkez_x + yaricap, merkez_y + yaricap),
        fill=BEYAZ,
        outline=(24, 30, 26),
        width=2,
    )
    leke = yaricap * 0.30
    ciz.ellipse(
        (merkez_x - leke, merkez_y - leke, merkez_x + leke, merkez_y + leke),
        fill=(24, 30, 26),
    )
    # Kenardaki üç küçük leke; bu boyutta top olarak okunuyor.
    for i in range(3):
        aci = -math.pi / 2 + i * (2 * math.pi / 3)
        lx = merkez_x + yaricap * 0.68 * math.cos(aci)
        ly = merkez_y + yaricap * 0.68 * math.sin(aci)
        kucuk = yaricap * 0.20
        ciz.ellipse((lx - kucuk, ly - kucuk, lx + kucuk, ly + kucuk),
                    fill=(24, 30, 26))


def _sayili_isaret(ciz, merkez_x, merkez_y, sayi: int, font, zemin) -> None:
    """Rakamlı küçük rozet (2+ gol / asist için)."""
    yazisi = str(sayi)
    _, ust, _, alt = ciz.textbbox((0, 0), yazisi, font=font)
    yukseklik = alt - ust
    yaricap = yukseklik * 0.85
    ciz.ellipse(
        (merkez_x - yaricap, merkez_y - yaricap, merkez_x + yaricap, merkez_y + yaricap),
        fill=zemin,
        outline=(255, 255, 255, 190),
        width=2,
    )
    _ortala(ciz, yazisi, font, merkez_x, merkez_y - yukseklik / 2 - ust, BEYAZ)


def _oyuncu_ciz(gorsel, ciz, oyuncu: dict, takim_kodu: str, merkez: tuple[int, int],
                olcu: Yerlesim) -> None:
    """
    Tek bir oyuncu kartı.

    İşaretlerin yeri sitedeki dizilim tahtasıyla aynı, yoksa aynı maça iki
    yerden bakınca farklı okunuyor:
        sol üst   kart          sağ üst   gol
        sol alt   maçın adamı   sağ alt   asist
        diskin altında puan, onun altında ad
    """
    mx, my = merkez
    yaricap = olcu.kart_yaricap
    capi = yaricap * 2

    disk_renk = TAKIM_RENKLERI[takim_kodu]
    yazi_renk = TAKIM_YAZI[takim_kodu]

    # --- Disk -----------------------------------------------------------
    ciz.ellipse(
        (mx - yaricap - 3, my - yaricap - 3, mx + yaricap + 3, my + yaricap + 3),
        fill=(0, 0, 0, 70),
    )

    profil = getattr(oyuncu["kullanici"], "profil", None)
    avatar = _avatar_diski(profil, capi)
    if avatar is not None:
        gorsel.paste(avatar, (mx - yaricap, my - yaricap), avatar)
        ciz.ellipse(
            (mx - yaricap, my - yaricap, mx + yaricap, my + yaricap),
            outline=disk_renk,
            width=3,
        )
    else:
        ciz.ellipse(
            (mx - yaricap, my - yaricap, mx + yaricap, my + yaricap),
            fill=disk_renk,
        )
        harf_font = metin_fontu(round(yaricap * 0.82))
        harfler = oyuncu["kullanici"].bas_harfler
        _, ust, _, alt = ciz.textbbox((0, 0), harfler, font=harf_font)
        _ortala(ciz, harfler, harf_font, mx, my - (alt - ust) / 2 - ust, yazi_renk)

    # --- Köşe işaretleri -------------------------------------------------
    kose = yaricap * 0.72  # köşelerin merkeze uzaklığı (45 derece)
    sapma = kose * 0.7071
    isaret_font = metin_fontu(round(olcu.rozet_boyutu * 0.86))

    if oyuncu.get("kart"):
        kart_g = round(yaricap * 0.42)
        kart_y = round(kart_g * 1.4)
        _kart_ciz(ciz, mx - sapma - kart_g / 2, my - sapma - kart_y / 2,
                  kart_g, kart_y, oyuncu["kart"])

    gol = oyuncu.get("gol") or 0
    if gol:
        top_r = yaricap * 0.30
        gx, gy = mx + sapma, my - sapma
        _top_ciz(ciz, gx, gy, top_r)
        if gol > 1:
            _sayili_isaret(ciz, gx + top_r * 1.1, gy - top_r * 0.9, gol,
                           isaret_font, (24, 30, 26))

    asist = oyuncu.get("asist") or 0
    if asist:
        # Asist: koyu mavi disk (sitedeki krampon işaretinin karşılığı).
        ax, ay = mx + sapma, my + sapma
        a_r = yaricap * 0.28
        ciz.ellipse((ax - a_r, ay - a_r, ax + a_r, ay + a_r),
                    fill=(32, 68, 100), outline=(230, 238, 244), width=2)
        if asist > 1:
            _sayili_isaret(ciz, ax + a_r * 1.1, ay + a_r * 0.9, asist,
                           isaret_font, (32, 68, 100))

    if oyuncu.get("macin_adami"):
        _yildiz_ciz(ciz, mx - sapma, my + sapma, yaricap * 0.40, (226, 185, 59))

    # --- Puan + ad tek şeritte -------------------------------------------
    #
    # İkisi alt alta ayrı rozetlerken kart o kadar uzuyordu ki, birbirine
    # yakın duran iki oyuncuda üsttekinin adı alttakinin diskinin altında
    # kalıyordu. Tek şeride alınca kartın boyu üçte bir kısaldı.
    ad_font = metin_fontu(olcu.ad_boyutu)
    puan_font = metin_fontu(olcu.rozet_boyutu)

    ad = _kisalt(ciz, _ilk_ad(oyuncu["kullanici"].gorunen_ad), ad_font, yaricap * 3.0)
    ad_g = _metin_genisligi(ciz, ad, ad_font)
    _, ad_ust, _, ad_alt = ciz.textbbox((0, 0), ad, font=ad_font)

    puan = oyuncu.get("puan")
    puan_yazisi = f"{puan:g}" if puan is not None else ""
    puan_g = (_metin_genisligi(ciz, puan_yazisi, puan_font) + 16) if puan_yazisi else 0

    kenar_bosluk = 10
    ara = 7 if puan_yazisi else 0
    serit_g = kenar_bosluk * 2 + puan_g + ara + ad_g
    serit_yuk = max(olcu.ad_boyutu, olcu.rozet_boyutu) + 14
    serit_ust = my + yaricap + 7
    serit_sol = mx - serit_g / 2

    ciz.rounded_rectangle(
        (serit_sol, serit_ust, serit_sol + serit_g, serit_ust + serit_yuk),
        radius=serit_yuk / 2,
        fill=(16, 26, 20, 220),
    )

    imlec = serit_sol + kenar_bosluk
    if puan_yazisi:
        zemin, yazi = PUAN_RENKLERI.get(
            oyuncu.get("puan_sinifi") or "", ((23, 25, 26), BEYAZ)
        )
        rozet_yuk = serit_yuk - 8
        rozet_ust = serit_ust + 4
        ciz.rounded_rectangle(
            (imlec, rozet_ust, imlec + puan_g, rozet_ust + rozet_yuk),
            radius=rozet_yuk / 2,
            fill=zemin,
        )
        _, ust, _, alt = ciz.textbbox((0, 0), puan_yazisi, font=puan_font)
        _ortala(ciz, puan_yazisi, puan_font, imlec + puan_g / 2,
                rozet_ust + (rozet_yuk - (alt - ust)) / 2 - ust, yazi)
        imlec += puan_g + ara

    ciz.text(
        (imlec, serit_ust + (serit_yuk - (ad_alt - ad_ust)) / 2 - ad_ust),
        ad,
        font=ad_font,
        fill=(246, 243, 234),
    )


def _konum(oyuncu: dict, kutu: tuple[int, int, int, int], dikey: bool) -> tuple[int, int]:
    """
    Yüzde konumu piksele çevirir.

    Dikeyde eksenler yer değiştiriyor: saklanan `x` yukarıdan aşağıya,
    `y` soldan sağa. Veri değişmiyor, yalnızca çizim eşlemesi değişiyor;
    telefonda kurulan dizilim bilgisayarda da aynı görünüyor.
    """
    sol, ust, sag, alt = kutu
    genislik, yukseklik = sag - sol, alt - ust
    # Kartlar kenardan taşmasın diye güvenli alan.
    pay = 0.06
    ic = lambda o: pay + (o / 100) * (1 - 2 * pay)  # noqa: E731

    if dikey:
        return (
            round(sol + ic(oyuncu["y"]) * genislik),
            round(ust + ic(oyuncu["x"]) * yukseklik),
        )
    return (
        round(sol + ic(oyuncu["x"]) * genislik),
        round(ust + ic(oyuncu["y"]) * yukseklik),
    )


# ---------------------------------------------------------------------------
# Başlık ve özet
# ---------------------------------------------------------------------------
def _baslik_ciz(ciz, mac, takimlar: list, olcu: Yerlesim, dikey: bool) -> None:
    sol = olcu.kenar
    sag = olcu.genislik - olcu.kenar
    y = olcu.kenar

    grup_font = baslik_fontu(56 if dikey else 50)
    tarih_font = metin_fontu(30 if dikey else 27)

    yerel = timezone.localtime(mac.baslangic)
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
             "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    tarih = f"{yerel.day} {aylar[yerel.month - 1]} {yerel.year}"
    if mac.konum:
        tarih += f" · {mac.konum}"

    if dikey:
        _ortala(ciz, _kisalt(ciz, mac.grup.ad, grup_font, sag - sol), grup_font,
                olcu.genislik / 2, y, MUREKKEP)
        _ortala(ciz, tarih, tarih_font, olcu.genislik / 2, y + 70, MUREKKEP_YUMUSAK)
        _skor_ciz(ciz, mac, takimlar, olcu.genislik / 2, y + 118, dikey=True)
    else:
        ciz.text((sol, y), _kisalt(ciz, mac.grup.ad, grup_font, (sag - sol) * 0.55),
                 font=grup_font, fill=MUREKKEP)
        ciz.text((sol, y + 62), tarih, font=tarih_font, fill=MUREKKEP_YUMUSAK)
        _skor_ciz(ciz, mac, takimlar, sag, y + 10, dikey=False)

    # İnce ayraç çizgi: defter havası.
    cizgi_y = olcu.kenar + olcu.baslik_yuksekligi - 16
    ciz.line((sol, cizgi_y, sag, cizgi_y), fill=CETVEL, width=2)


def _skor_ciz(ciz, mac, takimlar: list, x, y, dikey: bool) -> None:
    """Skor ve gerekiyorsa forma golü notu."""
    if not mac.skor_girildi_mi:
        return

    skor_font = baslik_fontu(66 if dikey else 58)
    not_font = metin_fontu(24)
    yazi = f"{mac.skor_a} - {mac.skor_b}"

    if dikey:
        _ortala(ciz, yazi, skor_font, x, y, MUREKKEP)
        alt_y = y + 78
    else:
        genislik = _metin_genisligi(ciz, yazi, skor_font)
        ciz.text((x - genislik, y), yazi, font=skor_font, fill=MUREKKEP)
        alt_y = y + 72

    # Forma golü yalnızca maçı belirlediğinde yazılıyor.
    if mac.forma_golu_belirledi_mi:
        adlar = dict(mac.Takim.choices)
        notu = f"Forma golü: {adlar[mac.forma_golu]}"
        if dikey:
            _ortala(ciz, notu, not_font, x, alt_y, HARDAL)
        else:
            ciz.text((x - _metin_genisligi(ciz, notu, not_font), alt_y),
                     notu, font=not_font, fill=HARDAL)


def _ozet_ciz(ciz, mac, takimlar: list, olcu: Yerlesim) -> None:
    """Takım adları, ortalama ve toplam."""
    sol = olcu.kenar
    sag = olcu.genislik - olcu.kenar
    ust = olcu.yukseklik - olcu.kenar - olcu.ozet_yuksekligi - olcu.alt_bilgi + 14

    ad_font = metin_fontu(30)
    sayi_font = baslik_fontu(38)
    etiket_font = metin_fontu(21)

    sutun = (sag - sol) / 2
    for i, takim in enumerate(takimlar):
        x0 = sol + i * sutun
        merkez = x0 + sutun / 2

        baslik = takim["ad"]
        if takim["kazandi"]:
            baslik += " · Kazandı"
        _ortala(ciz, baslik, ad_font, merkez, ust,
                MUREKKEP if takim["kazandi"] else MUREKKEP_YUMUSAK)

        if takim.get("ortalama_puan") is not None:
            _ortala(ciz, "Ortalama", etiket_font, merkez - sutun * 0.18, ust + 46,
                    MUREKKEP_SOLUK)
            _ortala(ciz, f"{takim['ortalama_puan']:g}", sayi_font,
                    merkez - sutun * 0.18, ust + 68, MUREKKEP)
            _ortala(ciz, "Toplam", etiket_font, merkez + sutun * 0.18, ust + 46,
                    MUREKKEP_SOLUK)
            _ortala(ciz, f"{takim['toplam_puan']:g}", sayi_font,
                    merkez + sutun * 0.18, ust + 68, MUREKKEP)

    # Ortadaki ayraç
    ciz.line((sol + sutun, ust - 4, sol + sutun, ust + olcu.ozet_yuksekligi - 30),
             fill=CETVEL, width=2)


def _alt_bilgi_ciz(ciz, olcu: Yerlesim) -> None:
    font = metin_fontu(22)
    y = olcu.yukseklik - olcu.kenar - 22
    ciz.text((olcu.kenar, y), "halisahadefteri.site", font=font, fill=MUREKKEP_SOLUK)


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------
def dizilim_gorseli(mac, takimlar: list, yon: str = YATAY) -> bytes:
    """
    Dizilimi PNG olarak çizer ve baytlarını döner.

    `takimlar`, `dizilim_verisi()` çıktısıdır; puan gizleme çağıran tarafta
    uygulanmış olarak gelir.
    """
    from PIL import Image, ImageDraw

    if yon not in YONLER:
        yon = YATAY

    olcu = _yerlesim(yon)
    dikey = yon == DIKEY

    gorsel = Image.new("RGB", (olcu.genislik, olcu.yukseklik), KAGIT)
    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # Kâğıt dokusu yerine ince bir çerçeve: defter sayfası hissi.
    ciz.rectangle(
        (10, 10, olcu.genislik - 11, olcu.yukseklik - 11),
        outline=CETVEL,
        width=2,
    )

    _baslik_ciz(ciz, mac, takimlar, olcu, dikey)

    kutu = olcu.saha_kutusu
    _saha_ciz(gorsel, kutu, dikey)
    ciz = ImageDraw.Draw(gorsel, "RGBA")

    # A takımı yatayda solda / dikeyde üstte; konumlar bunu zaten taşıyor.
    #
    # Yukarıdan aşağıya çiziliyor: iki oyuncu üst üste geldiğinde alttaki
    # kart üsttekinin ad etiketini örtüyor. Ters sırada isim, altındaki
    # oyuncunun diskinin üstünde asılı kalıyordu.
    kartlar = [
        (_konum(oyuncu, kutu, dikey), oyuncu, takim["kod"])
        for takim in takimlar
        for oyuncu in takim["oyuncular"]
    ]
    kartlar.sort(key=lambda k: k[0][1])
    for merkez, oyuncu, kod in kartlar:
        _oyuncu_ciz(gorsel, ciz, oyuncu, kod, merkez, olcu)

    _ozet_ciz(ciz, mac, takimlar, olcu)
    _alt_bilgi_ciz(ciz, olcu)

    tampon = io.BytesIO()
    gorsel.save(tampon, format="PNG", optimize=True)
    return tampon.getvalue()


# Dosya adı ASCII tutuluyor: Türkçe harf içeren bir ad Content-Disposition
# başlığında RFC 2047 ile kodlanıyor ("=?utf-8?q?per=C5=9Fembe...") ve
# tarayıcılar bunu dosya adı olarak farklı yorumluyor; kimi Android
# indiricileri de bozuk ad üretiyor.
ASCII_KARSILIKLARI = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
        "â": "a", "î": "i", "û": "u",
    }
)


def dosya_adi(mac, yon: str) -> str:
    """İndirilen dosyanın adı: grup ve tarih okunur olsun."""
    yerel = timezone.localtime(mac.baslangic)
    duz = mac.grup.ad.lower().translate(ASCII_KARSILIKLARI)
    temiz = "".join(h if h.isascii() and h.isalnum() else "-" for h in duz).strip("-")
    while "--" in temiz:
        temiz = temiz.replace("--", "-")
    return f"{temiz or 'dizilim'}-{yerel:%Y-%m-%d}-{yon}.png"
