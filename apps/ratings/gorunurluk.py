"""
Puanların kime görüneceği.

Kural: bir maçın puanlarını (oyuncu rozetleri, takım ortalaması/toplamı,
maçın adamı, sonuç tablosu) görebilmek için o maçta oynayan **herkesi**
puanlamış olmak gerekiyor.

Neden: puanlar gizli olduğu için insanlar kendi oylarını vermeden
başkalarının ortalamasına bakıp ona göre oy verebiliyordu. Ayrıca oy
vermeyi tamamen atlayıp yalnızca sonucu izlemek mümkündü.

İstisnalar:
  * Puanlama süresi dolduğunda (settings.RATING_WINDOW_DAYS) herkes görür.
    O noktada oy verilemediği için gizlemenin bir anlamı kalmıyor.
  * Nihai yönetici ve grup yöneticileri her zaman görür.

Sonradan kadroya eklenen oyuncu da listeye dâhil: o kişiye de puan
verilmeden puanlar yeniden gizlenir.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Puan


@dataclass(frozen=True)
class GorunurlukDurumu:
    gorebilir: bool
    # Kişinin henüz puanlamadığı oyuncular (kendisi hariç).
    eksik_oyuncular: list
    # Süre dolduğu için mi açık? Arayüzde farklı mesaj gösteriliyor.
    sure_doldu: bool
    yonetici_ayricaligi: bool

    @property
    def eksik_sayisi(self) -> int:
        return len(self.eksik_oyuncular)


def eksik_puanlar(mac, kullanici) -> list:
    """
    Kişinin bu maçta henüz puanlamadığı oyuncular.

    Kendisi listeye girmiyor (kimse kendine puan veremiyor). Karantinadaki
    puanlar VERİLMİŞ sayılıyor: oy kullanılmış, incelemesi ayrı bir konu.
    """
    if not kullanici or not kullanici.is_authenticated:
        return []

    oynayanlar = [
        k.kullanici
        for k in mac.oynayan_katilimlar()
        if k.kullanici_id != kullanici.pk
    ]
    puanlananlar = set(
        Puan.objects.filter(mac=mac, puanlayan=kullanici).values_list(
            "puanlanan_id", flat=True
        )
    )
    return [o for o in oynayanlar if o.pk not in puanlananlar]


def puan_gorunurlugu(mac, kullanici) -> GorunurlukDurumu:
    """Bu kişi bu maçın puanlarını görebilir mi?"""
    from django.utils import timezone

    sure_doldu = timezone.now() > mac.puanlama_bitis

    yonetici = bool(
        kullanici
        and kullanici.is_authenticated
        and (kullanici.is_superuser or mac.grup.yonetici_mi(kullanici))
    )

    if sure_doldu or yonetici:
        return GorunurlukDurumu(True, [], sure_doldu, yonetici)

    eksik = eksik_puanlar(mac, kullanici)
    return GorunurlukDurumu(not eksik, eksik, False, False)


def gizli_mac_idleri(grup, izleyen) -> set[int]:
    """
    Bu kişiye puanları kapalı olan maçların kimlikleri.

    Tek bir maçın sayfasını gizlemek yetmiyor: grup sıralaması, üye
    istatistikleri ve "form" ortalaması da aynı puanlardan besleniyor. Bir
    kişi kendi oyunu vermeden oradaki değişimden maçtaki puanı tahmin
    edebilirdi. Bu yüzden toplamlar hesaplanırken, o kişiye kapalı olan
    maçlar hesaba katılmıyor.

    Yalnızca puanlaması hâlâ açık maçlara bakılıyor; süresi dolmuş maç
    zaten herkese açık. Pratikte bu, son birkaç günün bir iki maçı demek.
    """
    from django.conf import settings
    from django.utils import timezone

    from apps.matches.models import Mac

    if not izleyen or not izleyen.is_authenticated:
        return set()
    if izleyen.is_superuser or grup.yonetici_mi(izleyen):
        return set()

    simdi = timezone.now()
    sinir = simdi - timezone.timedelta(days=settings.RATING_WINDOW_DAYS)
    acik_maclar = Mac.objects.filter(
        grup=grup, iptal=False, baslangic__gt=sinir, baslangic__lte=simdi
    )
    return {m.pk for m in acik_maclar if not puan_gorunurlugu(m, izleyen).gorebilir}


def kalan_yazim_haklari(mac, puanlayan) -> dict[int, int]:
    """
    Oyuncu kimliği -> o oyuncu için kalan puan yazma hakkı.

    Kayıt yoksa hak tamdır (henüz hiç yazılmamış). Sınır
    settings.RATING_MAX_WRITES; hak oyuncu bazında tutuluyor, yani sonradan
    eklenen birine yine iki hak var.
    """
    from django.conf import settings

    azami = settings.RATING_MAX_WRITES
    mevcut = {
        p.puanlanan_id: p.yazim_sayisi
        for p in Puan.objects.filter(mac=mac, puanlayan=puanlayan)
    }
    return {
        k.kullanici_id: max(0, azami - mevcut.get(k.kullanici_id, 0))
        for k in mac.oynayan_katilimlar()
        if k.kullanici_id != puanlayan.pk
    }
