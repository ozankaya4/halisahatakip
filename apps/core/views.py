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
from django.views.decorators.http import require_http_methods, require_POST

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
# Ana ekrana eklenebilir uygulama (PWA)
# ---------------------------------------------------------------------------
def cevrimdisi(request):
    """Ağ yokken servis çalışanının gösterdiği sayfa. İçinde kişisel veri yok."""
    return render(request, "core/cevrimdisi.html")


def favicon(request):
    """
    /favicon.ico — kararlı adresten site simgesi.

    Statik dosyalar içerik karmasıyla adlandırılıyor
    (favicon.a1b2c3.svg); o adres her CSS/ikon değişiminde kayıyor.
    Google arama sonucundaki site simgesini kararlı bir adresten okumak
    istiyor, üstelik tarayıcılar ve botlar doğrudan /favicon.ico deniyor.
    Bu yüzden kökten, sabit adla ve uzun önbellekle sunuyoruz.
    """
    return _statik_dosya(request, "img/favicon.ico", "image/x-icon")


def logo(request):
    """/logo.png — yapılandırılmış veride (JSON-LD) gösterilen kare logo."""
    return _statik_dosya(request, "img/logo-512.png", "image/png")


def _statik_dosya(request, goreli_yol: str, icerik_tipi: str) -> HttpResponse:
    """Statik bir dosyayı kararlı bir adresten sunar."""
    from django.contrib.staticfiles import finders

    yol = finders.find(goreli_yol)
    if not yol:
        raise Http404("Bulunamadı.")

    yanit = FileResponse(open(yol, "rb"), content_type=icerik_tipi)
    # Simge nadiren değişiyor; botlar ve tarayıcılar için uzun önbellek.
    yanit["Cache-Control"] = "public, max-age=604800"
    return yanit


def robots(request):
    """
    robots.txt.

    Sitenin neredeyse tamamı giriş gerektiriyor; taranacak tek şey tanıtım
    sayfası. Yine de faviconun ve logonun taranabilir olması şart: Google
    erişemediği bir simgeyi arama sonucunda göstermiyor.
    """
    return render(request, "core/robots.txt", content_type="text/plain")


def sitemap(request):
    """Site haritası. Herkese açık tek sayfa var: tanıtım sayfası."""
    return render(request, "core/sitemap.xml", content_type="application/xml")


def dijital_varlik_baglantilari(request):
    """
    /.well-known/assetlinks.json — Android uygulamasıyla alan adını eşleştirir.

    Play Store'daki uygulama bir TWA (Trusted Web Activity): aslında bu siteyi
    tam ekran açan ince bir Android kabuğu. Android, adres çubuğunu ancak bu
    dosyayı okuyup uygulamanın imza parmak izini burada bulursa gizliyor.
    Dosya yoksa ya da parmak izi tutmuyorsa uygulama üstünde tarayıcı çubuğu
    olan bir Chrome sekmesi gibi açılıyor.

    Parmak izi ayardan (ANDROID_SIGNING_FINGERPRINTS) geliyor, koda gömülü
    değil. Sebebi: uygulamayı Play'e yükledikten sonra Google onu KENDİ
    anahtarıyla yeniden imzalıyor, dolayısıyla buraya yazılması gereken
    parmak izi ancak Play Console'a ilk yükleme yapıldıktan sonra öğreniliyor.
    Ayar boşken dosya boş liste dönüyor; bu geçerli JSON ve zararsız.
    """
    from django.http import JsonResponse

    paket = settings.ANDROID_PACKAGE_NAME
    parmak_izleri = settings.ANDROID_SIGNING_FINGERPRINTS

    ifadeler = []
    if paket and parmak_izleri:
        ifadeler.append(
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": paket,
                    "sha256_cert_fingerprints": parmak_izleri,
                },
            }
        )

    yanit = JsonResponse(ifadeler, safe=False)
    # Android bu dosyayı uygulama her açıldığında değil, arada bir okuyor;
    # kısa önbellek yeni parmak izinin hızlı yayılmasını sağlıyor.
    yanit["Cache-Control"] = "public, max-age=300"
    return yanit


def hesap_silme(request):
    """
    Hesap silmenin herkese açık anlatımı.

    Silme işleminin kendisi accounts:hesabimi_sil sayfasında ve giriş
    istiyor. Play Console'a verilen "Hesap silme URL'si" ise oturum
    açmadan açılabilmeli: Google'ın incelemecisi adresi doğrudan ziyaret
    ediyor ve giriş duvarına çarparsa uygulama reddediliyor. Bu sayfa o
    yüzden var.
    """
    return render(request, "core/hesap_silme.html")


def kurallar(request):
    """
    İçerik kuralları.

    Play, kullanıcı içeriği barındıran uygulamalarda yazılı bir kural
    metni arıyor; "izin vermiyoruz" demenin tek geçerli hâli bu.
    """
    return render(request, "core/kurallar.html")


def gizlilik(request):
    """
    Gizlilik politikası.

    Play Store, hesap açan ve kişisel veri toplayan her uygulamada herkese
    açık (giriş gerektirmeyen) bir gizlilik politikası adresi istiyor;
    adresi olmayan uygulama yayına alınmıyor.
    """
    return render(request, "core/gizlilik.html")


def manifest(request):
    """
    Uygulama tanımı.

    Statik dosya yerine görünüm: nginx'in mime.types tablosunda .webmanifest
    yok, statik sunulduğunda yanlış içerik türüyle inip yok sayılıyor.
    """
    return render(
        request,
        "pwa/manifest.webmanifest",
        content_type="application/manifest+json",
    )


@require_http_methods(["GET"])
def servis_calisani(request):
    """
    Servis çalışanı dosyası.

    Kökten sunulmak ZORUNDA: bir servis çalışanının yetki alanı bulunduğu
    klasörle sınırlıdır. /static/js/sw.js olsaydı yalnızca /static/js/
    altındaki isteklere karışabilirdi.

    Cache-Control "no-cache": tarayıcı dosyayı her açılışta sunucuya sorar.
    Aksi hâlde servis çalışanının eski sürümü aylarca cihazda kalabiliyor ve
    yayınlanan düzeltmeler kullanıcıya ulaşmıyor.
    """
    yanit = render(request, "pwa/sw.js", content_type="text/javascript")
    yanit["Cache-Control"] = "no-cache, max-age=0"
    # Kökten sunulduğunu tarayıcıya açıkça bildiriyoruz.
    yanit["Service-Worker-Allowed"] = "/"
    return yanit


# ---------------------------------------------------------------------------
# Korumalı dosya sunumu
# ---------------------------------------------------------------------------
def _dosyayi_gonder(
    request, alan, indirilecek_ad: str, indir: bool = False
) -> HttpResponse:
    """
    Bir FieldFile'ı güvenli başlıklarla gönderir.

    Dosya adı ve yolu istekten değil veritabanından gelir. İçerik tipi
    tahmin edilmez; yalnızca bizim ürettiğimiz biçimlere izin verilir ve
    tarayıcının içeriği yeniden yorumlaması nosniff ile engellenir.

    indir=True verilirse tarayıcı dosyayı göstermek yerine kaydeder.
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

    # inline : sayfada görsel olarak gösterilsin
    # attachment: tarayıcı "kaydet" akışını başlatsın (telefonda galeriye iner)
    #
    # Sunucu tarafında karar veriyoruz; HTML'deki download özniteliğine
    # bırakmıyoruz. Sebebi: download özniteliği yalnızca aynı kaynaktaki
    # bağlantılarda ve bazı tarayıcılarda çalışıyor, iOS Safari'de ise
    # görmezden gelinip dosya yeni sekmede açılıyor. attachment başlığı
    # her yerde aynı davranıyor.
    #
    # Dosya adı ASCII'ye indirgenmiş hâliyle veriliyor: başlıkta Türkçe
    # karakter olursa bazı tarayıcılar adı bozuyor.
    if indir:
        yanit["Content-Disposition"] = f'attachment; filename="{indirilecek_ad}"'
    else:
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

    # ?indir=1 ile gelen istekte tarayıcı dosyayı kaydeder. Telefonda
    # galeriye/indirilenler klasörüne düşmesi için gereken tek şey bu.
    indir = request.GET.get("indir") == "1"

    # Kaydedilen dosyanın adı: karışık UUID yerine maçın tarihi.
    # Yalnızca ASCII: başlıkta Türkçe karakter bazı tarayıcılarda adı bozuyor.
    yerel = timezone.localtime(foto.mac.baslangic)
    ad = f"halisaha-{yerel:%Y-%m-%d}-{str(foto.dosya_id)[:8]}.webp"

    return _dosyayi_gonder(request, foto.dosya, ad, indir=indir)


# ---------------------------------------------------------------------------
# Hata sayfaları
# ---------------------------------------------------------------------------
def hata_403(request, exception=None):
    return render(request, "hatalar/403.html", status=403)


def hata_404(request, exception=None):
    return render(request, "hatalar/404.html", status=404)


def hata_500(request):
    return render(request, "hatalar/500.html", status=500)
