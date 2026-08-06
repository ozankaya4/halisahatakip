"""
Grup içi oyuncu istatistikleri.

Her sayı **yalnızca o gruba** aittir. Bir oyuncunun başka gruplardaki maçları,
golleri ve puanları buraya karışmaz; puanların gruba özel olmasının sebebiyle
aynı (bkz. apps/ratings/hesaplar.py).

İptal edilen maçlar hiçbir hesaba katılmaz: iptal, "bu maç olmamış sayılsın"
demek.
"""

from __future__ import annotations

from dataclasses import dataclass

GALIBIYET = "G"
BERABERLIK = "B"
MAGLUBIYET = "M"

# Son form şeridinde kaç maç gösterilecek.
SON_MAC_SAYISI = 5


@dataclass(frozen=True)
class MacSonucu:
    """Bir oyuncunun tek bir maçtaki sonucu ve puanı."""

    mac_id: int
    tarih: object
    sonuc: str  # "G" | "B" | "M"
    puan: float | None

    @property
    def etiket(self) -> str:
        return {GALIBIYET: "Galibiyet", BERABERLIK: "Beraberlik", MAGLUBIYET: "Mağlubiyet"}[
            self.sonuc
        ]

    @property
    def sinif(self) -> str:
        return {GALIBIYET: "sonuc-g", BERABERLIK: "sonuc-b", MAGLUBIYET: "sonuc-m"}[
            self.sonuc
        ]


def _seri_hesapla(sonuclar: list[str]) -> tuple[int, int]:
    """
    (güncel galibiyet serisi, en uzun galibiyet serisi).

    `sonuclar` en YENİDEN eskiye sıralı gelir. Güncel seri baştan sayılır;
    ilk galibiyet olmayan sonuçta biter.
    """
    guncel = 0
    for sonuc in sonuclar:
        if sonuc != GALIBIYET:
            break
        guncel += 1

    en_uzun = sayac = 0
    for sonuc in sonuclar:
        sayac = sayac + 1 if sonuc == GALIBIYET else 0
        en_uzun = max(en_uzun, sayac)

    return guncel, en_uzun


def uye_istatistikleri(grup, kullanici) -> dict:
    """
    Bir oyuncunun bu gruptaki bütün istatistikleri.

    Sorgu sayısı maç sayısından bağımsız: katılımlar, puanlar ve maçın adamı
    sayaçları toplu çekiliyor.
    """
    from apps.matches.dizilim import puan_rengi
    from apps.matches.models import Katilim, Mac
    from apps.ratings.denetim import grup_macin_adami_sayilari
    from apps.ratings.hesaplar import grup_ozeti
    from apps.ratings.models import Puan

    from django.db.models import Avg

    # --- Grubun maçları ve oyuncunun katılımları --------------------------
    toplam_mac = Mac.objects.filter(grup=grup, iptal=False, baslangic__lt=_simdi()).count()

    katilimlar = list(
        Katilim.objects.filter(
            mac__grup=grup, mac__iptal=False, kullanici=kullanici
        )
        .select_related("mac")
        .order_by("-mac__baslangic")
    )
    oynadiklari = [k for k in katilimlar if k.oynadi_mi and k.mac.gecmis_mi]

    # --- Maç bazlı puanlar (tek sorgu) ------------------------------------
    puan_haritasi = {
        satir["mac_id"]: round(satir["ortalama"], 1)
        for satir in Puan.objects.filter(
            puanlanan=kullanici, mac__grup=grup, mac__iptal=False, karantinada=False
        )
        .values("mac_id")
        .annotate(ortalama=Avg("deger"))
    }

    # --- Sonuç dizisi ------------------------------------------------------
    sonuclar: list[MacSonucu] = []
    for katilim in oynadiklari:
        mac = katilim.mac
        if not mac.skor_girildi_mi or not katilim.takim:
            continue  # sonucu bilinmeyen maç seriye girmez

        if mac.berabere_mi:
            sonuc = BERABERLIK
        elif mac.kazanan_takim == katilim.takim:
            sonuc = GALIBIYET
        else:
            sonuc = MAGLUBIYET

        sonuclar.append(
            MacSonucu(
                mac_id=mac.pk,
                tarih=mac.baslangic,
                sonuc=sonuc,
                puan=puan_haritasi.get(mac.pk),
            )
        )

    sonuc_kodlari = [s.sonuc for s in sonuclar]
    guncel_seri, en_uzun_seri = _seri_hesapla(sonuc_kodlari)

    # --- Puan özetleri -----------------------------------------------------
    ozet = grup_ozeti(grup, kullanici)
    mac_puanlari = [s.puan for s in sonuclar if s.puan is not None]
    son_puanlar = [p for p in mac_puanlari[:SON_MAC_SAYISI]]

    form_ortalamasi = (
        round(sum(son_puanlar) / len(son_puanlar), 2) if son_puanlar else None
    )
    en_yuksek = max(mac_puanlari) if mac_puanlari else None

    # --- Gol / asist / kart ------------------------------------------------
    gol = sum(k.gol for k in oynadiklari)
    asist = sum(k.asist for k in oynadiklari)
    sari = sum(k.sari_kart for k in oynadiklari)
    kirmizi = sum(1 for k in oynadiklari if k.kirmizi_kart)

    oynanan = len(oynadiklari)
    macin_adami_sayisi = grup_macin_adami_sayilari(grup).get(kullanici.pk, 0)

    return {
        "kullanici": kullanici,
        "grup": grup,
        # Katılım
        "toplam_mac": toplam_mac,
        "oynanan_mac": oynanan,
        "katilim_orani": round(100 * oynanan / toplam_mac) if toplam_mac else 0,
        # Sonuçlar
        "son_maclar": sonuclar[:SON_MAC_SAYISI],
        "galibiyet": sonuc_kodlari.count(GALIBIYET),
        "beraberlik": sonuc_kodlari.count(BERABERLIK),
        "maglubiyet": sonuc_kodlari.count(MAGLUBIYET),
        "sonuclu_mac": len(sonuc_kodlari),
        "guncel_seri": guncel_seri,
        "en_uzun_seri": en_uzun_seri,
        "galibiyet_orani": (
            round(100 * sonuc_kodlari.count(GALIBIYET) / len(sonuc_kodlari))
            if sonuc_kodlari
            else 0
        ),
        # Puanlar
        "ortalama": ozet["ortalama"],
        "oy_sayisi": ozet["adet"],
        "ortalama_gosterilsin": ozet["gosterilsin"],
        "ortalama_sinifi": puan_rengi(ozet["ortalama"]) if ozet["gosterilsin"] else "",
        "form_ortalamasi": form_ortalamasi,
        "form_sinifi": puan_rengi(form_ortalamasi),
        "en_yuksek_puan": en_yuksek,
        "en_yuksek_sinifi": puan_rengi(en_yuksek),
        "macin_adami": macin_adami_sayisi,
        # İstatistikler — görünürlük grup ayarına bağlı (dizilimdeki kuralın aynısı)
        "gol": gol if grup.gol_gosterilsin else None,
        "asist": asist if grup.asist_gosterilsin else None,
        "gol_basina_mac": (
            round(gol / oynanan, 2) if grup.gol_gosterilsin and oynanan else None
        ),
        "sari_kart": sari if grup.kart_gosterilsin else None,
        "kirmizi_kart": kirmizi if grup.kart_gosterilsin else None,
    }


def _simdi():
    from django.utils import timezone

    return timezone.now()
