"""
Oy manipülasyonuna karşı koruma.

Sorun: bir kişi herkese 10 verip arkadaşlarının ortalamasını şişirebilir ya
da herkese 1 verip düşürebilir. Tek tek puanlar gizli olduğu için bunu
kimse fark etmez.

Yaklaşım iki kademeli, çünkü "herkese aynı puanı verdi" her zaman
kötü niyet değildir:

  1. BARİZ durum (herkese aynı UÇ değer: hepsine 10 ya da hepsine 1)
     Otomatik silinir. Bunun masum bir açıklaması yok: on kişilik bir maçta
     herkesin tam olarak 10 ya da tam olarak 1 oynaması mümkün değil.

  2. ŞÜPHELİ durum (dağılım yok ama uç da değil, örn. herkese 7)
     Silinmez, KARANTİNAYA alınır. Ortalamalara girmez ama kayıt durur;
     grup yöneticisi bakıp karar verir. On iki kişilik bir arkadaş grubunda
     birini haksız yere hile yapmakla suçlamak, engellediği hileden daha
     çok zarar verir.

Eşik: en az DENETIM_ESIGI oy. Altında değerlendirme yapılmaz, çünkü üç
kişiye 8 vermek istatistiksel olarak hiçbir şey ifade etmiyor.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from django.db.models import Avg, Q

from .models import Puan

# Bu sayıya ulaşmadan karar verilmez.
DENETIM_ESIGI = 10

# "Uç" sayılan değerler: bu puanların hepsine aynı anda verilmesi bariz.
UC_DEGERLER = {1, 10}

# Standart sapma bunun altındaysa "dağılım yok" sayılır. 0.0 = tamamen aynı.
SAPMA_ESIGI = 0.35


@dataclass(frozen=True)
class DenetimSonucu:
    karar: str  # "temiz" | "supheli" | "bariz"
    oy_sayisi: int
    ortalama: float
    sapma: float
    gerekce: str

    @property
    def temiz_mi(self) -> bool:
        return self.karar == "temiz"


def _oylari_degerlendir(degerler: list[int]) -> DenetimSonucu:
    adet = len(degerler)
    ortalama = statistics.fmean(degerler)
    sapma = statistics.pstdev(degerler) if adet > 1 else 0.0
    benzersiz = set(degerler)

    if adet < DENETIM_ESIGI:
        return DenetimSonucu("temiz", adet, ortalama, sapma, "Yeterli oy yok.")

    # 1. Bariz: herkese aynı uç değer.
    if len(benzersiz) == 1 and degerler[0] in UC_DEGERLER:
        return DenetimSonucu(
            "bariz",
            adet,
            ortalama,
            sapma,
            f"{adet} oyuncunun hepsine {degerler[0]} verilmiş.",
        )

    # 2. Şüpheli: dağılım yok denecek kadar az.
    if sapma <= SAPMA_ESIGI:
        return DenetimSonucu(
            "supheli",
            adet,
            ortalama,
            sapma,
            f"{adet} oyuncuya neredeyse aynı puan verilmiş "
            f"(ortalama {ortalama:.1f}, sapma {sapma:.2f}).",
        )

    return DenetimSonucu("temiz", adet, ortalama, sapma, "Olağan dağılım.")


def mac_oylarini_denetle(mac, puanlayan) -> DenetimSonucu:
    """
    Bir kişinin TEK BİR maçtaki oylarını değerlendirir ve gereğini yapar.

    Puanlar kaydedildikten hemen sonra çağrılır. Döndürdüğü sonuç çağıran
    tarafın kullanıcıya ne söyleyeceğini belirler.
    """
    from apps.notifications.models import Bildirim, bildir, toplu_bildir

    kayitlar = list(
        Puan.objects.filter(mac=mac, puanlayan=puanlayan).order_by("id")
    )
    if not kayitlar:
        return DenetimSonucu("temiz", 0, 0.0, 0.0, "Oy yok.")

    sonuc = _oylari_degerlendir([k.deger for k in kayitlar])
    if sonuc.temiz_mi:
        return sonuc

    yoneticiler = [
        u.kullanici
        for u in mac.grup.onayli_uyelikler
        if u.yonetici_mi and u.kullanici_id != puanlayan.pk
    ]
    mac_adresi = mac.get_absolute_url()

    if sonuc.karar == "bariz":
        # Silmeden önce kimlerin etkilendiğini not al: ortalamalarını
        # yeniden hesaplamak gerekiyor.
        etkilenen = {k.puanlanan_id for k in kayitlar}
        Puan.objects.filter(mac=mac, puanlayan=puanlayan).delete()
        _profilleri_tazele(etkilenen)

        bildir(
            puanlayan,
            Bildirim.Tur.PUANLARIN_SILINDI,
            "Bu maçtaki puanların silindi",
            "Bütün oyunculara aynı uç puanı verdiğin için puanların "
            "geçersiz sayıldı. Puanlama süresi açıksa yeniden oy verebilirsin.",
            mac_adresi,
        )
        toplu_bildir(
            yoneticiler,
            Bildirim.Tur.SUPHELI_OYLAMA,
            f"{puanlayan.gorunen_ad} için oy uyarısı",
            f"{sonuc.gerekce} Puanlar otomatik olarak silindi.",
            mac_adresi,
        )
        return sonuc

    # Şüpheli: karantina. Silmiyoruz, yalnızca ortalamalardan çıkarıyoruz.
    Puan.objects.filter(mac=mac, puanlayan=puanlayan).update(karantinada=True)
    _profilleri_tazele({k.puanlanan_id for k in kayitlar})

    toplu_bildir(
        yoneticiler,
        Bildirim.Tur.SUPHELI_OYLAMA,
        f"{puanlayan.gorunen_ad} oyları incelemeni bekliyor",
        f"{sonuc.gerekce} Puanlar ortalamalara katılmıyor; "
        f"onaylarsan silinir, uygun görürsen geri alınır.",
        mac_adresi,
    )
    return sonuc


def _profilleri_tazele(kullanici_idleri) -> None:
    from apps.accounts.models import Profil

    for profil in Profil.objects.filter(kullanici_id__in=list(kullanici_idleri)):
        profil.istatistikleri_yenile()


def karantinadaki_oylar(grup):
    """Bir gruptaki karantina kayıtları, oy veren kişiye göre gruplanmış."""
    kayitlar = (
        Puan.objects.filter(karantinada=True, mac__grup=grup)
        .select_related("puanlayan", "mac", "puanlanan")
        .order_by("mac__baslangic", "puanlayan__ad_soyad", "id")
    )

    gruplar: dict[tuple[int, int], dict] = {}
    for kayit in kayitlar:
        anahtar = (kayit.mac_id, kayit.puanlayan_id)
        if anahtar not in gruplar:
            gruplar[anahtar] = {
                "mac": kayit.mac,
                "puanlayan": kayit.puanlayan,
                "puanlar": [],
            }
        gruplar[anahtar]["puanlar"].append(kayit)

    for veri in gruplar.values():
        degerler = [p.deger for p in veri["puanlar"]]
        veri["adet"] = len(degerler)
        veri["ortalama"] = round(statistics.fmean(degerler), 2)
    return list(gruplar.values())


def karantinayi_coz(mac, puanlayan, sil: bool) -> int:
    """
    Yöneticinin kararını uygular.

    sil=True  : puanlar gerçekten silinir (hile onaylandı)
    sil=False : karantina kalkar, puanlar ortalamalara geri döner
    """
    from apps.notifications.models import Bildirim, bildir

    sorgu = Puan.objects.filter(mac=mac, puanlayan=puanlayan, karantinada=True)
    etkilenen = set(sorgu.values_list("puanlanan_id", flat=True))
    adet = sorgu.count()
    if not adet:
        return 0

    if sil:
        sorgu.delete()
        bildir(
            puanlayan,
            Bildirim.Tur.PUANLARIN_SILINDI,
            "Bu maçtaki puanların silindi",
            "Grup yöneticisi oylarını inceledi ve geçersiz saydı.",
            mac.get_absolute_url(),
        )
    else:
        sorgu.update(karantinada=False)

    _profilleri_tazele(etkilenen)
    return adet


# ---------------------------------------------------------------------------
# Maçın adamı
# ---------------------------------------------------------------------------
def _en_iyileri_sec(adaylar: dict[int, float]) -> list[int]:
    """
    {kullanici_id: ortalama} içinden en yüksek olan(lar)ı döner.

    Eşitlikte hepsi döner: maçın adamı yıldızı paylaşılır.
    """
    if not adaylar:
        return []
    en_yuksek = max(adaylar.values())
    return [kid for kid, deger in adaylar.items() if deger == en_yuksek]


def _mac_adaylari(kazanan_takim, katilimlar, puanlar: dict) -> dict[int, float]:
    """
    Bir maçta maçın adamı olabilecek oyuncular ve maç ortalamaları.

    Kazanan varsa yalnızca o takım; beraberlikte iki takım da.
    `macin_adami` ile `grup_macin_adami_sayilari` bu kuralı ortak kullanıyor
    ki iki yerde iki farklı sonuç çıkmasın.
    """
    adaylar = {}
    for katilim in katilimlar:
        if kazanan_takim and katilim.takim != kazanan_takim:
            continue
        ortalama = puanlar.get(katilim.kullanici_id)
        if ortalama is not None:
            adaylar[katilim.kullanici_id] = ortalama
    return adaylar


def grup_macin_adami_sayilari(grup) -> dict[int, int]:
    """
    Gruptaki her oyuncunun kaç kez maçın adamı olduğu.

    Her maç için `macin_adami()` çağırmak maç sayısı kadar sorgu demek.
    Burada üç sorguyla tüm veriyi çekip hesabı Python'da yapıyoruz; kurallar
    `_mac_adaylari` / `_en_iyileri_sec` üzerinden paylaşıldığı için tek maçlık
    hesapla aynı sonucu veriyor.
    """
    from apps.matches.models import Katilim, Mac

    maclar = list(
        Mac.objects.filter(grup=grup, iptal=False)
        .exclude(skor_a=None)
        .exclude(skor_b=None)
    )
    if not maclar:
        return {}

    mac_idleri = [m.pk for m in maclar]

    # Tüm maçların puan ortalamaları tek sorguda.
    puan_haritasi: dict[int, dict[int, float]] = {}
    for satir in (
        Puan.objects.filter(mac_id__in=mac_idleri, karantinada=False)
        .values("mac_id", "puanlanan_id")
        .annotate(ortalama=Avg("deger"))
    ):
        puan_haritasi.setdefault(satir["mac_id"], {})[satir["puanlanan_id"]] = satir[
            "ortalama"
        ]

    # Sahaya çıkanlar tek sorguda.
    katilim_haritasi: dict[int, list] = {}
    for katilim in Katilim.objects.filter(mac_id__in=mac_idleri).exclude(takim=""):
        if katilim.oynadi_mi:
            katilim_haritasi.setdefault(katilim.mac_id, []).append(katilim)

    sayilar: dict[int, int] = {}
    for mac in maclar:
        adaylar = _mac_adaylari(
            mac.kazanan_takim,
            katilim_haritasi.get(mac.pk, []),
            puan_haritasi.get(mac.pk, {}),
        )
        for kullanici_id in _en_iyileri_sec(adaylar):
            sayilar[kullanici_id] = sayilar.get(kullanici_id, 0) + 1

    return sayilar


def macin_adami(mac) -> list:
    """
    Maçın adamı (adamları).

    Kural:
      * Skor girilmişse ve galip varsa: KAZANAN TAKIMIN en yüksek ortalamalı
        oyuncusu.
      * Beraberlikte: iki takım arasından en yüksek ortalamalı oyuncu.
      * Eşitlik: hepsi birden alır (yıldız paylaşılır).

    Karantinadaki puanlar sayılmaz. Skor girilmemişse ödül verilmez:
    galibi bilmeden "kazanan takımın en iyisi" hesaplanamaz.
    """
    from django.db.models import Avg, Count

    if mac.iptal or not mac.skor_girildi_mi:
        return []

    kazanan = mac.kazanan_takim
    katilimlar = mac.oynayan_katilimlar()
    if kazanan:
        katilimlar = katilimlar.filter(takim=kazanan)

    adaylar = (
        katilimlar.annotate(
            mac_ortalama=Avg(
                "kullanici__aldigi_puanlar__deger",
                filter=Q(kullanici__aldigi_puanlar__mac=mac)
                & Q(kullanici__aldigi_puanlar__karantinada=False),
            ),
            oy_adedi=Count(
                "kullanici__aldigi_puanlar",
                filter=Q(kullanici__aldigi_puanlar__mac=mac)
                & Q(kullanici__aldigi_puanlar__karantinada=False),
            ),
        )
        .filter(oy_adedi__gt=0)
        .select_related("kullanici", "kullanici__profil")
    )

    en_iyi = None
    kazananlar = []
    for katilim in adaylar:
        deger = round(katilim.mac_ortalama, 2)
        if en_iyi is None or deger > en_iyi:
            en_iyi = deger
            kazananlar = [katilim]
        elif deger == en_iyi:
            kazananlar.append(katilim)

    return [
        {"kullanici": k.kullanici, "ortalama": round(k.mac_ortalama, 2)}
        for k in kazananlar
    ]
