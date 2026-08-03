"""Çekirdek görünümler: anasayfa, panel, tema ve korumalı dosya sunumu."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .context_processors import GECERLI_TEMALAR, TEMA_COOKIE

guvenlik_log = logging.getLogger("halisaha.guvenlik")

# Sunulmasına izin verilen dosya türleri. Yükleme hattı her şeyi WEBP'ye
# çevirdiği için pratikte tek geçerli tür .webp; diğerleri eski kayıtlar için.
IZINLI_ICERIK_TIPLERI = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
}


def anasayfa(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return render(request, "core/anasayfa.html")


@login_required
def panel(request):
    """Kullanıcının gruplarını, yaklaşan maçlarını ve bekleyen işlerini toplar."""
    from apps.groups.models import Grup, Uyelik
    from apps.matches.models import Mac

    uyelikler = (
        Uyelik.objects.filter(kullanici=request.user, durum=Uyelik.Durum.ONAYLI)
        .select_related("grup")
        .order_by("grup__ad")
    )
    grup_idleri = [u.grup_id for u in uyelikler]

    yaklasan_maclar = (
        Mac.objects.filter(grup_id__in=grup_idleri, baslangic__gte=timezone.now())
        .select_related("grup")
        .order_by("baslangic")[:5]
    )

    puanlanabilir = [
        mac
        for mac in Mac.objects.filter(
            grup_id__in=grup_idleri, baslangic__lt=timezone.now()
        )
        .select_related("grup")
        .order_by("-baslangic")[:20]
        if mac.puanlama_acik and mac.kullanici_puanlayabilir(request.user)
    ][:5]

    yonetilen_gruplar = [u.grup for u in uyelikler if u.yonetici_mi]
    bekleyen_istek_sayisi = Uyelik.objects.filter(
        grup__in=yonetilen_gruplar, durum=Uyelik.Durum.BEKLIYOR
    ).count()

    return render(
        request,
        "core/panel.html",
        {
            "uyelikler": uyelikler,
            "yaklasan_maclar": yaklasan_maclar,
            "puanlanabilir_maclar": puanlanabilir,
            "bekleyen_istek_sayisi": bekleyen_istek_sayisi,
            "grup_yok": not uyelikler,
        },
    )


@require_POST
def tema_degistir(request):
    """Açık/koyu tema tercihini çereze yazar."""
    tema = request.POST.get("tema", "acik")
    if tema not in GECERLI_TEMALAR:
        tema = "acik"

    hedef = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(
        hedef, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        hedef = "/"

    yanit = HttpResponseRedirect(hedef)
    yanit.set_cookie(
        TEMA_COOKIE,
        tema,
        max_age=60 * 60 * 24 * 365,
        samesite="Lax",
        secure=request.is_secure(),
        httponly=False,
    )
    return yanit


# ---------------------------------------------------------------------------
# Korumalı dosya sunumu
# ---------------------------------------------------------------------------
def _dosyayi_gonder(request, alan, indirilecek_ad: str) -> HttpResponse:
    """
    Bir FieldFile'ı güvenli başlıklarla gönderir.

    Dosya adı ve yolu istekten değil veritabanından gelir. İçerik tipi
    tahmin edilmez; yalnızca bizim ürettiğimiz biçimlere izin verilir ve
    tarayıcının içeriği yeniden yorumlaması nosniff ile engellenir.
    """
    if not alan:
        raise Http404("Dosya yok.")

    yol = Path(alan.path)
    kok = Path(settings.MEDIA_ROOT).resolve()
    try:
        cozulmus = yol.resolve(strict=True)
    except (OSError, RuntimeError):
        raise Http404("Dosya bulunamadı.")

    # Kuşak-ve-kemer: kayıt bozulmuş olsa bile MEDIA_ROOT dışına çıkılamaz.
    if not cozulmus.is_relative_to(kok) or not cozulmus.is_file():
        guvenlik_log.warning(
            "MEDIA_ROOT dışına işaret eden dosya kaydı engellendi: %s", cozulmus
        )
        raise Http404("Dosya bulunamadı.")

    # İçerik tipini sistemin mimetypes tablosuna bırakmıyoruz: Windows'ta
    # .webp kayıtlı olmayabiliyor ve dosya application/octet-stream olarak
    # inmeye başlıyor. Zaten yalnızca kendi ürettiğimiz biçimler söz konusu.
    icerik_tipi = IZINLI_ICERIK_TIPLERI.get(
        cozulmus.suffix.lower(), "application/octet-stream"
    )

    if settings.USE_X_ACCEL_REDIRECT:
        # nginx'e devret: Django dosyayı okumaz, yalnızca yetkiyi doğrular.
        yanit = HttpResponse(status=200)
        goreli = cozulmus.relative_to(kok).as_posix()
        yanit["X-Accel-Redirect"] = f"/korumali-medya/{goreli}"
        yanit["Content-Type"] = icerik_tipi
    else:
        yanit = FileResponse(open(cozulmus, "rb"), content_type=icerik_tipi)

    # inline: görsel olarak gösterilsin; ama tarayıcı türü kendi tahmin etmesin.
    yanit["Content-Disposition"] = f'inline; filename="{indirilecek_ad}"'
    yanit["X-Content-Type-Options"] = "nosniff"
    yanit["Content-Security-Policy"] = "default-src 'none'; sandbox; img-src 'self'"
    yanit["Cache-Control"] = "private, max-age=3600"
    yanit["Cross-Origin-Resource-Policy"] = "same-origin"
    return yanit


def avatar_dosyasi(request, dosya_id):
    from apps.accounts.models import Profil

    if not request.user.is_authenticated and not settings.PUBLIC_PROFILES:
        raise Http404("Bulunamadı.")

    try:
        profil = Profil.objects.get(avatar_id=dosya_id)
    except Profil.DoesNotExist:
        raise Http404("Bulunamadı.")

    return _dosyayi_gonder(request, profil.avatar, "profil.webp")


@login_required
def mac_fotografi(request, dosya_id):
    from apps.groups.models import Uyelik
    from apps.matches.models import MacFotografi

    try:
        foto = MacFotografi.objects.select_related("mac").get(dosya_id=dosya_id)
    except MacFotografi.DoesNotExist:
        raise Http404("Bulunamadı.")

    # Maç fotoğrafları yalnızca o grubun onaylı üyelerine açıktır.
    if not request.user.is_superuser:
        yetkili = Uyelik.objects.filter(
            grup_id=foto.mac.grup_id,
            kullanici=request.user,
            durum=Uyelik.Durum.ONAYLI,
        ).exists()
        if not yetkili:
            raise Http404("Bulunamadı.")

    return _dosyayi_gonder(request, foto.dosya, "mac-fotografi.webp")


# ---------------------------------------------------------------------------
# Hata sayfaları
# ---------------------------------------------------------------------------
def hata_403(request, exception=None):
    return render(request, "hatalar/403.html", status=403)


def hata_404(request, exception=None):
    return render(request, "hatalar/404.html", status=404)


def hata_500(request):
    return render(request, "hatalar/500.html", status=500)
