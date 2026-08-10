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
# geliyor ve bu, puanlama ekranında açıkça yazıyor. 5-6 bandı sarı, yani
# "ortalama" rengi; altı kırmızıya ve siyaha, üstü yeşilden mora gidiyor.
#
# Aralıklar üst sınır dışta (alt <= puan < ust) ve BOŞLUKSUZ; her puan
# tam olarak bir renge denk geliyor. En üst aralık 10 dâhil.
PUAN_RENKLERI = [
    (0.0, 3.0, "puan-siyah"),
    (3.0, 5.0, "puan-kirmizi"),
    (5.0, 6.0, "puan-sari"),
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


# Takımların saha üzerindeki yarıları. Kartlar tam kenara yapışmasın diye
# uçlarda pay bırakılıyor; ayrıca bir takımın oyuncusu rakip yarıya
# geçemiyor (yönetici sürüklerken de, kayıt sırasında da kısıtlanıyor).
TAKIM_ARALIKLARI = {
    "a": (4, 47),
    "b": (53, 96),
}


def takim_araligi(takim: str) -> tuple[int, int]:
    """Takımın yerleşebileceği yatay aralık. Takımsızsa tüm saha."""
    return TAKIM_ARALIKLARI.get(takim, (0, 100))


def x_kirp(deger: int, takim: str) -> int:
    """X konumunu takımın yarısına hapseder."""
    alt, ust = takim_araligi(takim)
    return max(alt, min(ust, deger))


def kart_turu(katilim) -> tuple[str, str]:
    """
    Gösterilecek kart ve açıklaması.

    İki sarı gören oyuncunun kartı, doğrudan kırmızı görenden ayrı
    gösteriliyor: futbolda ikisi farklı şeyler ve karneye farklı yazılır.

    Öncelik sırası:
      2+ sarı  -> ikinci sarıdan kırmızı (sarı/kırmızı bölünmüş kart)
      kırmızı  -> doğrudan kırmızı
      1 sarı   -> sarı
    """
    if katilim.sari_kart >= 2:
        return "ikinci-sari", "İkinci sarıdan kırmızı"
    if katilim.kirmizi_kart:
        return "kirmizi", "Kırmızı kart"
    if katilim.sari_kart == 1:
        return "sari", "Sarı kart"
    return "", ""


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
                # Eski kayıtlar takım yarısı kuralından önce girilmiş
                # olabilir; gösterirken de kırpıyoruz ki karışık görünmesin.
                x, y = x_kirp(katilim.poz_x, kod), max(0, min(100, katilim.poz_y))

            puan = puanlar.get(katilim.kullanici_id)
            kart, kart_yazisi = kart_turu(katilim) if grup.kart_gosterilsin else ("", "")

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
                    "kart": kart,
                    "kart_yazisi": kart_yazisi,
                }
            )

        # Takımın puan toplamı ve ortalaması. Yalnızca puanı olan oyuncular
        # hesaba giriyor; puanlanmamış biri ortalamayı aşağı çekmemeli.
        puanlilar = [o["puan"] for o in oyuncular if o["puan"] is not None]
        toplam = round(sum(puanlilar), 1) if puanlilar else None
        ortalama = round(sum(puanlilar) / len(puanlilar), 1) if puanlilar else None

        takimlar.append(
            {
                "kod": kod,
                "ad": ad,
                "oyuncular": oyuncular,
                "skor": mac.skor_a if kod == Mac.Takim.A else mac.skor_b,
                "kazandi": mac.kazanan_takim == kod,
                "toplam_puan": toplam,
                "ortalama_puan": ortalama,
                "ortalama_sinifi": puan_rengi(ortalama),
                "puanli_oyuncu": len(puanlilar),
            }
        )

    return takimlar


def puanlari_gizle(takimlar: list) -> list:
    """
    Puanla ilgili her şeyi listeden çıkarır.

    Maçta oynayan herkesi puanlamamış kişiye dizilim gösteriliyor ama
    puanlar gösterilmiyor. Gizleme ŞABLONDA değil burada yapılıyor: veriyi
    hiç göndermezsek sayfa kaynağında da görünmez, "gizli ama HTML'de var"
    durumu oluşmaz.
    """
    for takim in takimlar:
        takim["toplam_puan"] = None
        takim["ortalama_puan"] = None
        takim["ortalama_sinifi"] = ""
        takim["puanli_oyuncu"] = 0
        for oyuncu in takim["oyuncular"]:
            oyuncu["puan"] = None
            oyuncu["puan_sinifi"] = ""
            # Maçın adamı da puanlardan çıkıyor: kimin en yüksek aldığını
            # ele verirdi.
            oyuncu["macin_adami"] = False
    return takimlar
