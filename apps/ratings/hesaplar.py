"""
Puan hesaplamaları — hepsi **grup bazında**.

Neden grup bazında: ortalama tek bir küresel sayı olsaydı, herkes kendi
grubunu kurup istediği puanı vererek profilindeki ortalamayı şişirebilirdi.
Puan yalnızca verildiği grubun içinde anlam taşır; farklı grupların puanları
birbirine karışmaz ve toplanmaz.

Ortalamalar önbelleğe alınmıyor, sorgu anında hesaplanıyor. Bu ölçekte
(bir grup birkaç düzine oyuncu) maliyeti yok ve önbellek tazeleme hatası
riski de ortadan kalkıyor: silinen bir maçın puanı ortalamada asla takılı
kalmaz.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Avg, Count, Q

from .models import Puan

# Hiçbir hesaba katılmayanlar:
#   * iptal edilmiş maçların puanları
#   * karantinadaki puanlar (şüpheli oylama, yönetici kararı bekliyor)
GECERLI_PUAN = Q(mac__iptal=False) & Q(karantinada=False)


def grup_ozeti(grup, kullanici, izleyen=None) -> dict:
    """
    Bir kullanıcının **tek bir gruptaki** puan özeti.

    `izleyen` verilirse, o kişiye kapalı olan maçlar (puanlamasını
    tamamlamadığı, süresi henüz dolmamış maçlar) hesaba katılmaz; yoksa
    ortalamadaki oynama üzerinden maçtaki puan tahmin edilebilirdi.
    Bkz. apps/ratings/gorunurluk.py::gizli_mac_idleri.

    Döner: {"ortalama": Decimal|None, "adet": int, "gosterilsin": bool}
    """
    from .gorunurluk import gizli_mac_idleri

    sorgu = Puan.objects.filter(GECERLI_PUAN, puanlanan=kullanici, mac__grup=grup)
    gizli = gizli_mac_idleri(grup, izleyen) if izleyen is not None else set()
    if gizli:
        sorgu = sorgu.exclude(mac_id__in=gizli)

    ozet = sorgu.aggregate(ortalama=Avg("deger"), adet=Count("id"))

    adet = ozet["adet"] or 0
    ortalama = round(ozet["ortalama"], 2) if ozet["ortalama"] is not None else None
    return {
        "ortalama": ortalama,
        "adet": adet,
        "gosterilsin": ortalama is not None
        and adet >= settings.RATING_MIN_VOTES_TO_DISPLAY,
    }


def kullanicinin_grup_ozetleri(kullanici, gruplar, izleyen=None) -> list[dict]:
    """
    Kullanıcının verilen gruplardaki özetleri, ortalaması yüksekten düşüğe.

    `gruplar` çağıran tarafça sınırlandırılır: profil sayfasında yalnızca
    bakan kişinin de üyesi olduğu gruplar veriliyor, böylece kimse
    başkasının hangi gruplarda oynadığını profil üzerinden öğrenemiyor.
    """
    satirlar = []
    for grup in gruplar:
        ozet = grup_ozeti(grup, kullanici, izleyen=izleyen)
        if ozet["adet"] == 0:
            continue
        satirlar.append({"grup": grup, **ozet})

    satirlar.sort(key=lambda s: (s["ortalama"] is None, -(s["ortalama"] or 0)))
    return satirlar


def grup_siralamasi(grup, limit: int | None = None, izleyen=None) -> list[dict]:
    """
    Grubun kendi puan sıralaması.

    Yalnızca o grupta oynanan maçlardan gelen puanlar sayılır ve eşiğin
    altında oy almış oyuncular listelenmez (az oyla oluşan ortalama
    yanıltıcıdır).

    `izleyen`e kapalı maçlar sıralamaya girmez (bkz. `grup_ozeti`).
    """
    from apps.groups.models import Uyelik

    from .gorunurluk import gizli_mac_idleri

    gizli = gizli_mac_idleri(grup, izleyen) if izleyen is not None else set()
    gizleme = (
        ~Q(kullanici__aldigi_puanlar__mac_id__in=gizli) if gizli else Q()
    )

    uyelikler = (
        Uyelik.objects.filter(grup=grup, durum=Uyelik.Durum.ONAYLI)
        .select_related("kullanici", "kullanici__profil")
        .annotate(
            grup_ortalama=Avg(
                "kullanici__aldigi_puanlar__deger",
                filter=Q(kullanici__aldigi_puanlar__mac__grup=grup)
                & Q(kullanici__aldigi_puanlar__mac__iptal=False)
                & Q(kullanici__aldigi_puanlar__karantinada=False)
                & gizleme,
            ),
            grup_oy_sayisi=Count(
                "kullanici__aldigi_puanlar",
                filter=Q(kullanici__aldigi_puanlar__mac__grup=grup)
                & Q(kullanici__aldigi_puanlar__mac__iptal=False)
                & Q(kullanici__aldigi_puanlar__karantinada=False)
                & gizleme,
            ),
        )
        .filter(grup_oy_sayisi__gte=settings.RATING_MIN_VOTES_TO_DISPLAY)
        .order_by("-grup_ortalama", "kullanici__ad_soyad")
    )

    if limit is not None:
        uyelikler = uyelikler[:limit]

    return [
        {
            "uyelik": u,
            "kullanici": u.kullanici,
            "ortalama": round(u.grup_ortalama, 2) if u.grup_ortalama is not None else None,
            "adet": u.grup_oy_sayisi,
        }
        for u in uyelikler
    ]


def mac_puanlarini_sil(mac) -> int:
    """
    Bir maçın tüm puanlarını siler ve etkilenen profillerin sayaçlarını tazeler.

    Maç iptal edildiğinde ya da silindiğinde çağrılır. Amaç: oynanmamış bir
    maçtan puan biriktirilememesi. Silinen kayıt sayısını döner.
    """
    from apps.accounts.models import Profil

    etkilenen = list(
        Puan.objects.filter(mac=mac).values_list("puanlanan_id", flat=True).distinct()
    )
    silinen, _ = Puan.objects.filter(mac=mac).delete()

    for profil in Profil.objects.filter(kullanici_id__in=etkilenen):
        profil.istatistikleri_yenile()

    return silinen
