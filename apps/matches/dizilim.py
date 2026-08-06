"""
Maç dizilimi: sahadaki oyuncu yerleşimi ve maç puanları.

Dizilim maç oynandıktan sonra açılır. Yönetici oyuncuları sahada sürükleyerek
yerleştirir; herkes sonucu görür. Her oyuncunun O MAÇTAKİ ortalaması
fotoğrafının köşesinde renkli bir rozet olarak görünür.

Konumlar piksel değil yüzde olarak saklanıyor (0-100). Saha telefonda dar,
masaüstünde geniş çiziliyor; yüzde her ikisinde de aynı noktaya denk geliyor.
"""

from __future__ import annotations

from django.db.models import Avg, Count, Q

# Puan aralıkları ve renk sınıfları.
#
# Ölçeğin ortası 5: oyuncuya "vasat bir maç çıkardı" demek 5 vermek anlamına
# geliyor ve bu, puanlama ekranında açıkça yazıyor. Renkler de buna göre
# dağıtıldı; 5 nötr (gri) bölgenin içinde kalıyor, iyi performanslar yukarı
# doğru yeşilden mora çıkıyor.
#
# Aralıklar üst sınır dışta (alt <= puan < ust) ve BOŞLUKSUZ; her puan
# tam olarak bir renge denk geliyor. En üst aralık 10 dâhil.
PUAN_RENKLERI = [
    (0.0, 2.0, "puan-siyah"),
    (2.0, 4.0, "puan-kirmizi"),
    (4.0, 6.0, "puan-gri"),
    (6.0, 7.0, "puan-yesil"),
    (7.0, 8.0, "puan-mavi"),
    (8.0, 9.0, "puan-lacivert"),
]
# 9 ve üstü mor. Ayrı tutuluyor çünkü üst sınırı kapalı (10 dâhil).
UST_ARALIK_SINIFI = "puan-mor"

# Ölçeğin ortası. Arayüzde "5 ortalamadır" açıklaması buradan besleniyor.
ORTALAMA_PUAN = 5


def puan_rengi(deger) -> str:
    """Bir maç ortalamasının renk sınıfı. Puan yoksa boş dizge."""
    if deger is None:
        return ""
    deger = float(deger)
    if deger >= 9.0:
        return UST_ARALIK_SINIFI
    for alt, ust, sinif in PUAN_RENKLERI:
        if alt <= deger < ust:
            return sinif
    return ""


def _varsayilan_konum(sira: int, toplam: int, takim: str) -> tuple[int, int]:
    """
    Yerleştirilmemiş oyuncular için makul bir başlangıç noktası.

    Takımlar sahanın iki yarısına dağıtılıyor: A solda, B sağda. Böylece
    yönetici boş bir sahayla değil, düzeltilecek bir dizilimle başlıyor.
    """
    from .models import Mac

    # Kaleci en geride, gerisi iki sıraya bölünür.
    if sira == 0:
        x_oran = 0.08
        y = 50
    else:
        kalan = max(toplam - 1, 1)
        sutun = (sira - 1) % 2  # iki sıra
        satir = (sira - 1) // 2
        satir_sayisi = max((kalan + 1) // 2, 1)
        x_oran = 0.22 + sutun * 0.16
        y = int(100 * (satir + 1) / (satir_sayisi + 1))

    x = int(100 * x_oran) if takim == Mac.Takim.A else int(100 * (1 - x_oran))
    return max(4, min(96, x)), max(8, min(92, y))


def mac_puan_haritasi(mac) -> dict[int, float]:
    """Oyuncu kimliği -> o maçtaki ortalama puanı (karantinadakiler hariç)."""
    from apps.ratings.models import Puan

    ozet = (
        Puan.objects.filter(mac=mac, karantinada=False)
        .values("puanlanan_id")
        .annotate(ortalama=Avg("deger"), adet=Count("id"))
    )
    return {
        satir["puanlanan_id"]: round(satir["ortalama"], 1)
        for satir in ozet
        if satir["adet"]
    }


def dizilim_verisi(mac, macin_adami_idleri: set[int] | None = None) -> list[dict]:
    """
    Sahada çizilecek takımlar ve oyuncular.

    Her oyuncu için: konum, maç puanı, puan rengi, istatistikler ve maçın
    adamı olup olmadığı. Şablon bu listeyi olduğu gibi basıyor.
    """
    from .models import Mac

    macin_adami_idleri = macin_adami_idleri or set()
    puanlar = mac_puan_haritasi(mac)
    grup = mac.grup

    takimlar = []
    for kod, ad in Mac.Takim.choices:
        katilimlar = list(mac.takim_katilimlari(kod))
        oyuncular = []

        for sira, katilim in enumerate(katilimlar):
            if katilim.poz_x is None or katilim.poz_y is None:
                x, y = _varsayilan_konum(sira, len(katilimlar), kod)
            else:
                x, y = katilim.poz_x, katilim.poz_y

            puan = puanlar.get(katilim.kullanici_id)
            oyuncular.append(
                {
                    "katilim": katilim,
                    "kullanici": katilim.kullanici,
                    "x": x,
                    "y": y,
                    "puan": puan,
                    "puan_sinifi": puan_rengi(puan),
                    "macin_adami": katilim.kullanici_id in macin_adami_idleri,
                    # Görünürlük grup ayarına bağlı; şablon sadeleşsin diye
                    # kararı burada veriyoruz.
                    "gol": katilim.gol if grup.gol_gosterilsin else 0,
                    "asist": katilim.asist if grup.asist_gosterilsin else 0,
                    "sari_kart": katilim.sari_kart if grup.kart_gosterilsin else 0,
                    "kirmizi_kart": katilim.kirmizi_kart if grup.kart_gosterilsin else False,
                }
            )

        takimlar.append(
            {
                "kod": kod,
                "ad": ad,
                "oyuncular": oyuncular,
                "skor": mac.skor_a if kod == Mac.Takim.A else mac.skor_b,
                "kazandi": mac.kazanan_takim == kod,
            }
        )

    return takimlar
