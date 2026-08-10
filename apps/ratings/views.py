"""Puanlama görünümleri."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import Profil
from apps.core.ratelimit import sinir_asildi
from apps.groups.yetki import uye_gerekli
from apps.matches.models import Mac

from .denetim import karantinadaki_oylar, karantinayi_coz, mac_oylarini_denetle
from .gorunurluk import gizli_mac_idleri, kalan_yazim_haklari, puan_gorunurlugu
from .models import Puan


def _mac_ve_yetki(request, mac_id: int) -> Mac:
    mac = get_object_or_404(Mac.objects.select_related("grup"), pk=mac_id)
    if not (request.user.is_superuser or mac.grup.uye_mi(request.user)):
        raise PermissionDenied("Bu grubun üyesi değilsiniz.")
    return mac


@login_required
def puanla(request, mac_id: int):
    mac = _mac_ve_yetki(request, mac_id)

    if not mac.puanlama_acik:
        messages.info(request, mac.puanlama_durumu + ".")
        return redirect("matches:detay", mac_id=mac.pk)

    if not mac.kullanici_puanlayabilir(request.user):
        messages.error(
            request,
            "Bu maçta sahaya çıkmadığın için puan veremezsin. "
            "Kadroda olduğunu düşünüyorsan yöneticiye haber ver.",
        )
        return redirect("matches:detay", mac_id=mac.pk)

    # Kendisi hariç, maçta oynayan herkes.
    oynayanlar = [
        k.kullanici for k in mac.oynayan_katilimlar() if k.kullanici_id != request.user.pk
    ]
    oynayanlar.sort(key=lambda k: k.gorunen_ad.lower())

    mevcut = {
        p.puanlanan_id: p.deger
        for p in Puan.objects.filter(mac=mac, puanlayan=request.user)
    }
    oyuncular_haritasi = {k.pk: k.gorunen_ad for k in oynayanlar}

    if request.method == "POST":
        if sinir_asildi(f"puan:{request.user.pk}:{mac.pk}", limit=15, saniye=600):
            messages.error(request, "Çok sık kaydediyorsun, biraz bekle.")
            return redirect("ratings:puanla", mac_id=mac.pk)

        gecerli_idler = {k.pk for k in oynayanlar}
        kaydedilecek: dict[int, int] = {}
        hatali = False

        for anahtar, ham in request.POST.items():
            if not anahtar.startswith("puan_"):
                continue
            try:
                oyuncu_id = int(anahtar.removeprefix("puan_"))
            except ValueError:
                continue
            if oyuncu_id not in gecerli_idler:
                # Formda olmayan biri gönderilmiş: sessizce at.
                continue
            if ham == "":
                continue
            try:
                deger = int(ham)
            except ValueError:
                hatali = True
                continue
            if not (1 <= deger <= 10):
                hatali = True
                continue
            kaydedilecek[oyuncu_id] = deger

        if hatali:
            messages.error(request, "Puanlar 1 ile 10 arasında olmalı.")
            return redirect("ratings:puanla", mac_id=mac.pk)

        if not kaydedilecek:
            messages.info(request, "Hiç puan girmedin.")
            return redirect("matches:detay", mac_id=mac.pk)

        azami_yazim = settings.RATING_MAX_WRITES
        yazilanlar: dict[int, int] = {}
        kilitliler: list[str] = []

        with transaction.atomic():
            mevcut_kayitlar = {
                p.puanlanan_id: p
                for p in Puan.objects.select_for_update().filter(
                    mac=mac, puanlayan=request.user, puanlanan_id__in=kaydedilecek
                )
            }

            for oyuncu_id, deger in kaydedilecek.items():
                kayit = mevcut_kayitlar.get(oyuncu_id)

                if kayit is None:
                    Puan.objects.create(
                        mac=mac,
                        puanlayan=request.user,
                        puanlanan_id=oyuncu_id,
                        deger=deger,
                        yazim_sayisi=1,
                    )
                    yazilanlar[oyuncu_id] = deger
                    continue

                # Aynı değeri yeniden kaydetmek hak yakmaz. Form herkesi
                # birden gönderdiği için, tek bir oyuncuyu düzelten kişi
                # aksi hâlde diğerlerinin hakkını da harcamış olurdu.
                if kayit.deger == deger:
                    continue

                if kayit.yazim_sayisi >= azami_yazim:
                    kilitliler.append(
                        oyuncular_haritasi.get(oyuncu_id, "bir oyuncu")
                    )
                    continue

                kayit.deger = deger
                kayit.yazim_sayisi += 1
                kayit.save(update_fields=["deger", "yazim_sayisi", "guncellenme"])
                yazilanlar[oyuncu_id] = deger

            # Etkilenen oyuncuların profil ortalamalarını tazele.
            for profil in Profil.objects.filter(kullanici_id__in=yazilanlar):
                profil.istatistikleri_yenile()

        if kilitliler:
            messages.warning(
                request,
                "Şu oyuncular için puan değiştirme hakkın doldu, "
                "puanları olduğu gibi kaldı: " + ", ".join(sorted(kilitliler)) + ". "
                f"Her oyuncuya en fazla {azami_yazim} kez puan yazılabiliyor.",
            )

        # Oy dağılımını denetle. Herkese aynı uç puanı verildiyse puanlar
        # silinir; dağılımsız ama uç olmayan durumlarda karantinaya alınıp
        # yöneticiye bildirilir. Ayrıntılar: apps/ratings/denetim.py
        denetim = mac_oylarini_denetle(mac, request.user)

        if denetim.karar == "bariz":
            messages.error(
                request,
                "Bütün oyunculara aynı uç puanı verdiğin için puanların "
                "kaydedilmedi. Puanlar oyuncuları birbirinden ayırmak için var; "
                "süre dolmadan yeniden değerlendirebilirsin.",
            )
        elif denetim.karar == "supheli":
            messages.warning(
                request,
                "Puanların kaydedildi ama birbirine çok yakın olduğu için "
                "şimdilik ortalamalara katılmıyor. Grup yöneticisi bakıp "
                "onaylayacak.",
            )
        elif yazilanlar:
            messages.success(
                request, f"{len(yazilanlar)} oyuncu için puanların kaydedildi."
            )
        elif not kilitliler:
            messages.info(request, "Puanlarında değişiklik yoktu.")

        # Herkesi puanlamayan kişi puanları göremiyor; sonuç sayfası yerine
        # eksiklerini görebileceği maç sayfasına döndürüyoruz.
        durum = puan_gorunurlugu(mac, request.user)
        if durum.gorebilir:
            return redirect("ratings:sonuclar", mac_id=mac.pk)
        messages.info(
            request,
            f"Puanları görebilmek için {durum.eksik_sayisi} oyuncuyu daha "
            "puanlaman gerekiyor.",
        )
        return redirect("ratings:puanla", mac_id=mac.pk)

    kalan_haklar = kalan_yazim_haklari(mac, request.user)
    satirlar = [
        {
            "kullanici": k,
            "mevcut": mevcut.get(k.pk),
            "araliklar": range(1, 11),
            "kalan_hak": kalan_haklar.get(k.pk, settings.RATING_MAX_WRITES),
        }
        for k in oynayanlar
    ]
    kalan = mac.puanlama_bitis - timezone.now()

    return render(
        request,
        "ratings/puanla.html",
        {
            "mac": mac,
            "grup": mac.grup,
            "satirlar": satirlar,
            "kalan_gun": max(kalan.days, 0),
            "kalan_saat": max(kalan.seconds // 3600, 0),
            "zaten_puanladi": bool(mevcut),
        },
    )


@login_required
def sonuclar(request, mac_id: int):
    """
    Maçın puan ortalamaları.

    Kimin kime kaç verdiği hiçbir koşulda gösterilmez; yalnızca ortalama ve
    kaç kişinin oy verdiği görünür.
    """
    mac = _mac_ve_yetki(request, mac_id)

    pencere_kapandi = timezone.now() > mac.puanlama_bitis

    # Sonuçları görmek için maçta oynayan HERKESİ puanlamış olmak gerekiyor.
    # Eskiden tek bir oy yeterliydi; kişi bir kişiye puan verip geri kalanının
    # ortalamasını görebiliyor, sonra ona göre oy verebiliyordu.
    durum = puan_gorunurlugu(mac, request.user)
    gorunur = durum.gorebilir

    ozet = []
    if gorunur:
        ozet = list(
            Puan.objects.filter(mac=mac, karantinada=False)
            .values("puanlanan_id", "puanlanan__ad_soyad", "puanlanan__email")
            .annotate(ortalama=Avg("deger"), oy_sayisi=Count("id"))
            .order_by("-ortalama")
        )
        for satir in ozet:
            satir["ad"] = satir["puanlanan__ad_soyad"] or satir["puanlanan__email"].split("@")[0]
            satir["ortalama"] = round(satir["ortalama"], 2)
            satir["yuzde"] = round(satir["ortalama"] * 10)

    return render(
        request,
        "ratings/sonuclar.html",
        {
            "mac": mac,
            "grup": mac.grup,
            "ozet": ozet,
            "gorunur": gorunur,
            "pencere_kapandi": pencere_kapandi,
            "puanlayabilir": mac.kullanici_puanlayabilir(request.user),
            "durum": durum,
        },
    )


@uye_gerekli
def siralama(request, grup):
    """Grup içi genel sıralama — yalnızca ortalamalar."""
    # İptal edilen maçların ve karantinadaki oyların puanları sayılmaz.
    #
    # Puanlamasını tamamlamayan kişiye, o maçların puanları burada da
    # gösterilmiyor: sıralamayı maçtan önce ve sonra karşılaştıran biri
    # ortalamadaki oynamadan puanı çıkarabilirdi.
    gizli = gizli_mac_idleri(grup, request.user)
    satirlar = (
        Puan.objects.filter(mac__grup=grup, mac__iptal=False, karantinada=False)
        .exclude(mac_id__in=gizli)
        .values("puanlanan_id", "puanlanan__ad_soyad", "puanlanan__email")
        .annotate(ortalama=Avg("deger"), oy_sayisi=Count("id"))
        .order_by("-ortalama")
    )
    esik = settings.RATING_MIN_VOTES_TO_DISPLAY

    listelenen, yetersiz = [], []
    for satir in satirlar:
        satir["ad"] = satir["puanlanan__ad_soyad"] or satir["puanlanan__email"].split("@")[0]
        satir["ortalama"] = round(satir["ortalama"], 2)
        satir["yuzde"] = round(satir["ortalama"] * 10)
        (listelenen if satir["oy_sayisi"] >= esik else yetersiz).append(satir)

    return render(
        request,
        "ratings/siralama.html",
        {
            "grup": grup,
            "listelenen": listelenen,
            "yetersiz": yetersiz,
            "esik": esik,
            "gizli_mac_sayisi": len(gizli),
        },
    )


@uye_gerekli
def oy_incelemesi(request, grup):
    """
    Karantinaya alınmış oyların yönetici incelemesi.

    Buraya düşen puanlar ortalamalara ZATEN katılmıyor; yani karar
    verilene kadar kimse zarar görmüyor. Yönetici ya "hile" deyip siler ya
    da "sorun yok" deyip serbest bırakır.

    Tek tek puanların kime verildiği burada gösterilmiyor: puanlar gizli
    kalmalı. Yönetici yalnızca dağılımı görüyor, bu da karar için yeterli.
    """
    if not grup.yonetici_mi(request.user):
        raise PermissionDenied("Bu sayfa grup yöneticilerine açık.")

    if request.method == "POST":
        mac = get_object_or_404(Mac, pk=request.POST.get("mac"), grup=grup)
        puanlayan = get_object_or_404(
            get_user_model(), pk=request.POST.get("puanlayan")
        )
        sil = request.POST.get("karar") == "sil"
        adet = karantinayi_coz(mac, puanlayan, sil=sil)

        if not adet:
            messages.info(request, "Bu kayıt zaten sonuçlanmış.")
        elif sil:
            messages.success(
                request, f"{adet} puan silindi ve oyuncuya bildirildi."
            )
        else:
            messages.success(
                request, f"{adet} puan geçerli sayıldı ve ortalamalara katıldı."
            )
        return redirect("ratings:oy_incelemesi", genel_id=grup.genel_id)

    return render(
        request,
        "ratings/oy_incelemesi.html",
        {"grup": grup, "kayitlar": karantinadaki_oylar(grup)},
    )
