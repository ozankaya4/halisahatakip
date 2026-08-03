"""Puanlama görünümleri."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
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

        with transaction.atomic():
            for oyuncu_id, deger in kaydedilecek.items():
                Puan.objects.update_or_create(
                    mac=mac,
                    puanlayan=request.user,
                    puanlanan_id=oyuncu_id,
                    defaults={"deger": deger},
                )
            # Etkilenen oyuncuların profil ortalamalarını tazele.
            for profil in Profil.objects.filter(kullanici_id__in=kaydedilecek):
                profil.istatistikleri_yenile()

        messages.success(
            request, f"{len(kaydedilecek)} oyuncu için puanların kaydedildi."
        )
        return redirect("ratings:sonuclar", mac_id=mac.pk)

    satirlar = [
        {"kullanici": k, "mevcut": mevcut.get(k.pk), "araliklar": range(1, 11)}
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

    kendi_oyu_var = Puan.objects.filter(mac=mac, puanlayan=request.user).exists()
    pencere_kapandi = timezone.now() > mac.puanlama_bitis

    # Oyunu vermeden başkalarının ortalamasını görüp ona göre oy vermeyi
    # engellemek için sonuçlar ya oy verdikten sonra ya da pencere kapanınca
    # açılır.
    gorunur = kendi_oyu_var or pencere_kapandi or request.user.is_superuser

    ozet = []
    if gorunur:
        ozet = list(
            Puan.objects.filter(mac=mac)
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
        },
    )


@uye_gerekli
def siralama(request, grup):
    """Grup içi genel sıralama — yalnızca ortalamalar."""
    satirlar = (
        Puan.objects.filter(mac__grup=grup)
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
        },
    )
