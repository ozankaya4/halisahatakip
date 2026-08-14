"""
İçerik şikâyetleri: bildirme ve yönetici incelemesi.

Şikâyet eden kişi grubun onaylı üyesi olmak zorunda; şikâyeti inceleyen ise
grup yöneticisi. Nihai yönetici her grupta yönetici sayılıyor
(bkz. Grup.yonetici_mi).
"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.ratelimit import sinir_asildi
from apps.groups.yetki import yonetici_gerekli
from apps.matches.models import MacFotografi
from apps.notifications.models import Bildirim, toplu_bildir

from .models import Sikayet

# Şikâyet kutusunu doldurmaya karşı; bir kişi saatte bu kadar bildirebilir.
SAATLIK_SINIR = 20


def _uye_gerekli(kullanici, grup) -> None:
    if not grup.uye_mi(kullanici):
        raise PermissionDenied("Bu grubun üyesi değilsin.")


def _yoneticilere_haber_ver(sikayet: Sikayet) -> None:
    from apps.groups.models import Uyelik

    yoneticiler = [
        u.kullanici
        for u in Uyelik.objects.filter(
            grup=sikayet.grup,
            durum=Uyelik.Durum.ONAYLI,
            rol=Uyelik.Rol.YONETICI,
        ).select_related("kullanici")
        if u.kullanici_id != sikayet.bildiren_id
    ]
    toplu_bildir(
        yoneticiler,
        Bildirim.Tur.ICERIK_BILDIRILDI,
        f"“{sikayet.grup.ad}” · içerik bildirildi",
        f"{sikayet.get_tur_display()} · {sikayet.get_sebep_display()}",
        reverse("moderation:liste", kwargs={"genel_id": sikayet.grup.genel_id}),
    )


# ---------------------------------------------------------------------------
# Bildirme
# ---------------------------------------------------------------------------
@login_required
def fotograf_bildir(request, foto_id: int):
    foto = get_object_or_404(
        MacFotografi.objects.select_related("mac", "mac__grup"), pk=foto_id
    )
    grup = foto.mac.grup
    _uye_gerekli(request.user, grup)

    if foto.yukleyen_id == request.user.pk:
        messages.info(request, "Kendi yüklediğin fotoğrafı silebilirsin; bildirmene gerek yok.")
        return redirect("matches:detay", mac_id=foto.mac_id)

    if request.method == "POST":
        if sinir_asildi(f"sikayet:{request.user.pk}", limit=SAATLIK_SINIR, saniye=3600):
            messages.error(request, "Çok fazla bildirim gönderdin, biraz sonra tekrar dene.")
            return redirect("matches:detay", mac_id=foto.mac_id)

        sebep = request.POST.get("sebep", "")
        if sebep not in Sikayet.Sebep.values:
            messages.error(request, "Bir sebep seç.")
            return redirect("moderation:fotograf_bildir", foto_id=foto.pk)

        try:
            sikayet = Sikayet.objects.create(
                grup=grup,
                bildiren=request.user,
                tur=Sikayet.Tur.FOTOGRAF,
                sebep=sebep,
                aciklama=(request.POST.get("aciklama") or "")[:500],
                fotograf=foto,
            )
        except IntegrityError:
            messages.info(request, "Bu fotoğrafı zaten bildirmiştin.")
            return redirect("matches:detay", mac_id=foto.mac_id)

        _yoneticilere_haber_ver(sikayet)
        messages.success(
            request,
            "Bildirimin grup yöneticisine iletildi. Teşekkürler.",
        )
        return redirect("matches:detay", mac_id=foto.mac_id)

    return render(
        request,
        "moderation/bildir.html",
        {
            "grup": grup,
            "tur": "fotograf",
            "fotograf": foto,
            "sebepler": Sikayet.Sebep.choices,
            "geri_url": reverse("matches:detay", kwargs={"mac_id": foto.mac_id}),
        },
    )


@login_required
@require_POST
def mesaj_bildir(request, genel_id):
    """
    Sohbet mesajı şikâyeti — JSON.

    Metin, şikâyet edenin cihazında çözülmüş hâlde geliyor; sunucu şifreli
    mesajı kendi başına açamıyor (bkz. apps/moderation/models.py).
    """
    from apps.chat.models import Mesaj
    from apps.groups.models import Grup

    grup = get_object_or_404(Grup, genel_id=genel_id)
    _uye_gerekli(request.user, grup)

    if sinir_asildi(f"sikayet:{request.user.pk}", limit=SAATLIK_SINIR, saniye=3600):
        return JsonResponse(
            {"tamam": False, "hata": "Çok fazla bildirim gönderdin."}, status=429
        )

    try:
        veri = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"tamam": False, "hata": "Geçersiz istek."}, status=400)

    mesaj = get_object_or_404(Mesaj, pk=veri.get("mesaj_id"), grup=grup)
    if mesaj.gonderen_id == request.user.pk:
        return JsonResponse(
            {"tamam": False, "hata": "Kendi mesajını bildiremezsin."}, status=400
        )

    sebep = veri.get("sebep", "")
    if sebep not in Sikayet.Sebep.values:
        return JsonResponse({"tamam": False, "hata": "Bir sebep seç."}, status=400)

    try:
        sikayet = Sikayet.objects.create(
            grup=grup,
            bildiren=request.user,
            tur=Sikayet.Tur.MESAJ,
            sebep=sebep,
            aciklama=str(veri.get("aciklama") or "")[:500],
            mesaj=mesaj,
            mesaj_metni=str(veri.get("metin") or "")[:2000],
        )
    except IntegrityError:
        return JsonResponse({"tamam": True, "zaten": True})

    _yoneticilere_haber_ver(sikayet)
    return JsonResponse({"tamam": True})


# ---------------------------------------------------------------------------
# İnceleme
# ---------------------------------------------------------------------------
@yonetici_gerekli
def liste(request, grup):
    sikayetler = (
        Sikayet.objects.filter(grup=grup)
        .select_related("bildiren", "fotograf", "fotograf__mac", "mesaj", "mesaj__gonderen")
        .order_by("durum", "-olusturulma")
    )
    return render(
        request,
        "moderation/liste.html",
        {
            "grup": grup,
            "bekleyenler": [s for s in sikayetler if s.durum == Sikayet.Durum.BEKLIYOR],
            "gecmis": [s for s in sikayetler if s.durum != Sikayet.Durum.BEKLIYOR][:30],
        },
    )


@yonetici_gerekli
@require_POST
def karar(request, grup, sikayet_id: int):
    sikayet = get_object_or_404(Sikayet, pk=sikayet_id, grup=grup)
    islem = request.POST.get("islem")

    if sikayet.durum != Sikayet.Durum.BEKLIYOR:
        messages.info(request, "Bu bildirim zaten karara bağlanmış.")
        return redirect("moderation:liste", genel_id=grup.genel_id)

    if islem == "kaldir":
        # İçerik siliniyor; şikâyet kaydı duruyor ki geçmiş görülebilsin.
        if sikayet.tur == Sikayet.Tur.FOTOGRAF and sikayet.fotograf_id:
            sikayet.fotograf.delete()
            # Veritabanında SET_NULL uygulanıyor ama elimizdeki nesne hâlâ
            # silinmiş fotoğrafı gösteriyor; temizlenmezse Django kaydı
            # "kaydedilmemiş ilişkili nesne" diye reddediyor.
            sikayet.fotograf = None
        elif sikayet.tur == Sikayet.Tur.MESAJ and sikayet.mesaj_id:
            # Mesaj metni sunucuda şifreli; "silindi" işareti akıştan çıkarıyor.
            sikayet.mesaj.silindi = True
            sikayet.mesaj.save(update_fields=["silindi"])
        sikayet.durum = Sikayet.Durum.KALDIRILDI
        mesaj_metni = "İçerik kaldırıldı."
    elif islem == "reddet":
        sikayet.durum = Sikayet.Durum.REDDEDILDI
        mesaj_metni = "Bildirim kapatıldı; kural ihlali bulunmadı."
    else:
        messages.error(request, "Geçersiz işlem.")
        return redirect("moderation:liste", genel_id=grup.genel_id)

    sikayet.inceleyen = request.user
    sikayet.karar_tarihi = timezone.now()
    sikayet.karar_notu = (request.POST.get("karar_notu") or "")[:300]
    sikayet.save(
        update_fields=[
            "durum", "inceleyen", "karar_tarihi", "karar_notu",
            "fotograf", "guncellenme",
        ]
    )

    messages.success(request, mesaj_metni)
    return redirect("moderation:liste", genel_id=grup.genel_id)
