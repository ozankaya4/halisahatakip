"""
Sohbet görünümleri ve JSON uçları.

Bu dosyadaki hiçbir kod mesaj içeriğine bakmaz; yalnızca şifreli blobları
taşır, doğrular ve yetkilendirir. Şifreleme/çözme tamamen tarayıcıdadır
(static/js/e2ee.js).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.core.ratelimit import sinir_asildi
from apps.groups.models import Grup, Uyelik
from apps.moderation.models import Sikayet

from .models import MAX_SIFRELI_UZUNLUK, AnahtarCifti, AnahtarPaketi, GrupAnahtari, Mesaj
from .services import aktif_anahtar, eksik_paket_uyeleri, sonraki_surum

guvenlik_log = logging.getLogger("halisaha.guvenlik")

# Base64 alanları için üst sınırlar (kötü niyetli devasa gövdeleri erken keser).
MAX_ACIK_ANAHTAR = 4096
MAX_OZEL_ANAHTAR = 8192
MAX_SARMALANMIS = 2048
PBKDF2_EN_AZ_YINELEME = 200_000


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def _govde(request) -> dict:
    """İstek gövdesini JSON olarak çözer; bozuksa ValueError."""
    if len(request.body) > 512 * 1024:
        raise ValueError("Gövde çok büyük.")
    try:
        veri = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Geçersiz JSON.")
    if not isinstance(veri, dict):
        raise ValueError("Geçersiz gövde.")
    return veri


def _b64_dogrula(deger, azami: int, alan: str) -> str:
    """Base64 biçimini ve uzunluğunu doğrular. İçeriği çözmeye çalışmaz."""
    if not isinstance(deger, str) or not deger:
        raise ValueError(f"{alan} eksik.")
    if len(deger) > azami:
        raise ValueError(f"{alan} çok uzun.")
    try:
        base64.b64decode(deger, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(f"{alan} geçerli base64 değil.")
    return deger


def _grubu_getir(request, genel_id) -> Grup:
    grup = get_object_or_404(Grup, genel_id=genel_id)
    # Sohbet nihai yöneticiye de kapalıdır: üye değilse anahtar paketi yoktur,
    # zaten okuyamaz. Erişimi de vermiyoruz ki yanıltıcı olmasın.
    if not grup.uye_mi(request.user):
        raise Http404("Bulunamadı.")
    return grup


def _hata(mesaj: str, kod: int = 400) -> JsonResponse:
    return JsonResponse({"tamam": False, "hata": mesaj}, status=kod)


# ---------------------------------------------------------------------------
# Sayfalar
# ---------------------------------------------------------------------------
@login_required
def anahtar_kurulumu(request):
    """Şifreleme parolası belirleme / anahtarların kilidini açma sayfası."""
    var_mi = AnahtarCifti.objects.filter(kullanici=request.user).exists()
    return render(
        request,
        "chat/anahtar_kurulumu.html",
        {"anahtar_var": var_mi, "en_az_uzunluk": 12},
    )


@login_required
def sohbet(request, genel_id):
    grup = _grubu_getir(request, genel_id)
    anahtarim_var = AnahtarCifti.objects.filter(kullanici=request.user).exists()
    return render(
        request,
        "chat/sohbet.html",
        {
            "grup": grup,
            "anahtarim_var": anahtarim_var,
            "yonetici_mi": grup.yonetici_mi(request.user),
            "sayfa_boyutu": settings.MESSAGES_PAGE_SIZE,
            # Şikâyet kutusundaki sebep listesi; tek kaynaktan geliyor ki
            # şablonla model ayrışmasın.
            "sebepler": Sikayet.Sebep.choices,
        },
    )


# ---------------------------------------------------------------------------
# Kendi anahtar çiftim
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def api_kendi_anahtarim(request):
    if request.method == "GET":
        kayit = AnahtarCifti.objects.filter(kullanici=request.user).first()
        if kayit is None:
            return JsonResponse({"tamam": True, "var": False})
        return JsonResponse(
            {
                "tamam": True,
                "var": True,
                "sifreli_ozel_anahtar": kayit.sifreli_ozel_anahtar,
                "tuz": kayit.tuz,
                "iv": kayit.iv,
                "yineleme": kayit.yineleme,
                "acik_anahtar": json.loads(kayit.acik_anahtar),
                "parmak_izi": kayit.parmak_izi,
            }
        )

    # POST — anahtar çifti oluştur. Var olan anahtar sessizce ezilmez.
    if AnahtarCifti.objects.filter(kullanici=request.user).exists():
        return _hata(
            "Zaten bir anahtarın var. Değiştirmek için önce sıfırlaman gerekir.", 409
        )

    if sinir_asildi(f"anahtar:{request.user.pk}", limit=5, saniye=3600):
        return _hata("Çok fazla deneme. Bir süre sonra tekrar dene.", 429)

    try:
        veri = _govde(request)
        acik = veri.get("acik_anahtar")
        if not isinstance(acik, dict):
            raise ValueError("acik_anahtar geçersiz.")
        acik_metin = json.dumps(acik, separators=(",", ":"))
        if len(acik_metin) > MAX_ACIK_ANAHTAR:
            raise ValueError("Açık anahtar çok uzun.")
        if acik.get("kty") != "RSA" or acik.get("alg") != "RSA-OAEP-256":
            raise ValueError("Desteklenmeyen anahtar türü.")

        sifreli = _b64_dogrula(
            veri.get("sifreli_ozel_anahtar"), MAX_OZEL_ANAHTAR, "Şifreli özel anahtar"
        )
        tuz = _b64_dogrula(veri.get("tuz"), 64, "Tuz")
        iv = _b64_dogrula(veri.get("iv"), 32, "IV")

        yineleme = int(veri.get("yineleme", 0))
        if yineleme < PBKDF2_EN_AZ_YINELEME:
            raise ValueError("PBKDF2 yineleme sayısı çok düşük.")

        parmak_izi = str(veri.get("parmak_izi", ""))[:95]
    except (ValueError, TypeError) as hata:
        return _hata(str(hata))

    try:
        AnahtarCifti.objects.create(
            kullanici=request.user,
            acik_anahtar=acik_metin,
            sifreli_ozel_anahtar=sifreli,
            tuz=tuz,
            iv=iv,
            yineleme=yineleme,
            parmak_izi=parmak_izi,
        )
    except IntegrityError:
        return _hata("Zaten bir anahtarın var.", 409)

    return JsonResponse({"tamam": True})


@login_required
@require_POST
def api_anahtar_sifirla(request):
    """
    Anahtarları sıfırlar (şifreleme parolası unutulduğunda).

    Sonuç geri alınamaz: eski anahtarla şifrelenmiş tüm mesajlar bu kullanıcı
    için kalıcı olarak okunamaz hâle gelir. Bilerek yıkıcı bir işlemdir.
    """
    if sinir_asildi(f"anahtar_sifirla:{request.user.pk}", limit=3, saniye=3600):
        return _hata("Çok fazla deneme. Bir süre sonra tekrar dene.", 429)

    with transaction.atomic():
        AnahtarPaketi.objects.filter(uye=request.user).delete()
        AnahtarCifti.objects.filter(kullanici=request.user).delete()
        # Bu kişinin üyesi olduğu grupların anahtarları da döndürülmeli:
        # artık eski sürümleri açamayacağı için yeni sürüm gerekiyor.
        GrupAnahtari.objects.filter(
            grup__uyelikler__kullanici=request.user,
            grup__uyelikler__durum=Uyelik.Durum.ONAYLI,
            aktif=True,
        ).update(dondurulmeli=True)

    guvenlik_log.info("Kullanıcı anahtarlarını sıfırladı: %s", request.user.pk)
    return JsonResponse({"tamam": True})


# ---------------------------------------------------------------------------
# Grup anahtarı
# ---------------------------------------------------------------------------
@login_required
@require_GET
def api_durum(request, genel_id):
    """
    İstemcinin sohbeti kurmak için ihtiyaç duyduğu her şey.

    Buradan dönen `sarmalanmis` yalnızca isteği yapan kullanıcıya aittir;
    başka üyelerin paketleri asla gönderilmez.
    """
    grup = _grubu_getir(request, genel_id)
    anahtar = aktif_anahtar(grup)

    uyeler = []
    for uyelik in grup.onayli_uyelikler:
        kayit = AnahtarCifti.objects.filter(kullanici=uyelik.kullanici).first()
        uyeler.append(
            {
                "id": uyelik.kullanici_id,
                "ad": uyelik.kullanici.gorunen_ad,
                "acik_anahtar": json.loads(kayit.acik_anahtar) if kayit else None,
                "parmak_izi": kayit.parmak_izi if kayit else "",
            }
        )

    # Kendi tüm sürüm paketlerim: geçmiş mesajlar anahtar döndükten sonra da
    # okunabilsin diye eski sürümler de gönderilir. Yalnızca *bana ait*
    # paketler — başka üyelerinki asla.
    paketlerim = [
        {"surum": p.grup_anahtari.surum, "sarmalanmis": p.sarmalanmis}
        for p in AnahtarPaketi.objects.filter(
            grup_anahtari__grup=grup, uye=request.user
        ).select_related("grup_anahtari")
    ]

    yanit = {
        "tamam": True,
        "ben": request.user.pk,
        "uyeler": uyeler,
        "paketlerim": paketlerim,
        "anahtarsiz_uye_sayisi": sum(1 for u in uyeler if u["acik_anahtar"] is None),
    }

    if anahtar is None:
        yanit["anahtar"] = None
        yanit["sonraki_surum"] = sonraki_surum(grup)
        return JsonResponse(yanit)

    benim_paket = AnahtarPaketi.objects.filter(
        grup_anahtari=anahtar, uye=request.user
    ).first()

    yanit["anahtar"] = {
        "surum": anahtar.surum,
        "sarmalanmis": benim_paket.sarmalanmis if benim_paket else None,
    }
    yanit["sonraki_surum"] = anahtar.surum + 1
    yanit["eksik_uyeler"] = [
        {"id": u.kullanici_id, "ad": u.kullanici.gorunen_ad}
        for u in eksik_paket_uyeleri(grup, anahtar)
    ]
    return JsonResponse(yanit)


@login_required
@require_POST
def api_anahtar_yayinla(request, genel_id):
    """
    Yeni bir grup anahtarı sürümü yayınlar.

    Anahtar materyali istemcide üretilir; sunucuya yalnızca her üye için
    ayrı ayrı sarmalanmış hâlleri gelir.
    """
    grup = _grubu_getir(request, genel_id)

    if sinir_asildi(f"anahtar_yayin:{grup.pk}", limit=10, saniye=600):
        return _hata("Çok fazla anahtar yayını. Biraz bekle.", 429)

    try:
        veri = _govde(request)
        surum = int(veri.get("surum", 0))
        paketler = veri.get("paketler")
        if not isinstance(paketler, list) or not paketler:
            raise ValueError("Paket listesi boş.")
        if len(paketler) > 500:
            raise ValueError("Çok fazla paket.")
    except (ValueError, TypeError) as hata:
        return _hata(str(hata))

    gecerli_uyeler = set(
        Uyelik.objects.filter(grup=grup, durum=Uyelik.Durum.ONAYLI).values_list(
            "kullanici_id", flat=True
        )
    )

    temiz: dict[int, str] = {}
    try:
        for paket in paketler:
            if not isinstance(paket, dict):
                raise ValueError("Geçersiz paket.")
            uye_id = int(paket.get("uye_id", 0))
            if uye_id not in gecerli_uyeler:
                # Gruba ait olmayan biri için paket kabul edilmez.
                continue
            temiz[uye_id] = _b64_dogrula(
                paket.get("sarmalanmis"), MAX_SARMALANMIS, "Sarmalanmış anahtar"
            )
    except (ValueError, TypeError) as hata:
        return _hata(str(hata))

    if request.user.pk not in temiz:
        return _hata("Kendi paketin listede yok; anahtarı kaybederdin.")

    try:
        with transaction.atomic():
            son = (
                GrupAnahtari.objects.select_for_update()
                .filter(grup=grup)
                .order_by("-surum")
                .first()
            )
            beklenen = (son.surum + 1) if son else 1
            if surum != beklenen:
                # Aynı anda iki kişi anahtar üretmiş olabilir; istemci
                # durumu yeniden çekip tekrar denesin.
                return _hata(
                    f"Sürüm çakışması (beklenen {beklenen}). Sayfayı yenile.", 409
                )

            GrupAnahtari.objects.filter(grup=grup, aktif=True).update(aktif=False)
            anahtar = GrupAnahtari.objects.create(
                grup=grup, surum=beklenen, olusturan=request.user, aktif=True
            )
            AnahtarPaketi.objects.bulk_create(
                [
                    AnahtarPaketi(grup_anahtari=anahtar, uye_id=uye_id, sarmalanmis=blob)
                    for uye_id, blob in temiz.items()
                ]
            )
    except IntegrityError:
        return _hata("Anahtar yayınlanamadı, tekrar dene.", 409)

    return JsonResponse({"tamam": True, "surum": anahtar.surum})


@login_required
@require_POST
def api_paket_ekle(request, genel_id):
    """Aktif anahtarı, henüz paketi olmayan üyeler için sarmalayıp ekler."""
    grup = _grubu_getir(request, genel_id)
    anahtar = aktif_anahtar(grup)
    if anahtar is None:
        return _hata("Aktif anahtar yok.")

    try:
        veri = _govde(request)
        surum = int(veri.get("surum", 0))
        paketler = veri.get("paketler")
        if surum != anahtar.surum:
            return _hata("Sürüm eskimiş. Sayfayı yenile.", 409)
        if not isinstance(paketler, list) or not paketler or len(paketler) > 500:
            raise ValueError("Geçersiz paket listesi.")
    except (ValueError, TypeError) as hata:
        return _hata(str(hata))

    gecerli_uyeler = set(
        Uyelik.objects.filter(grup=grup, durum=Uyelik.Durum.ONAYLI).values_list(
            "kullanici_id", flat=True
        )
    )
    mevcut = set(
        AnahtarPaketi.objects.filter(grup_anahtari=anahtar).values_list("uye_id", flat=True)
    )

    eklenecek = []
    try:
        for paket in paketler:
            uye_id = int(paket.get("uye_id", 0))
            if uye_id not in gecerli_uyeler or uye_id in mevcut:
                continue
            eklenecek.append(
                AnahtarPaketi(
                    grup_anahtari=anahtar,
                    uye_id=uye_id,
                    sarmalanmis=_b64_dogrula(
                        paket.get("sarmalanmis"), MAX_SARMALANMIS, "Sarmalanmış anahtar"
                    ),
                )
            )
    except (ValueError, TypeError, AttributeError) as hata:
        return _hata(str(hata))

    if eklenecek:
        AnahtarPaketi.objects.bulk_create(eklenecek, ignore_conflicts=True)

    return JsonResponse({"tamam": True, "eklenen": len(eklenecek)})


# ---------------------------------------------------------------------------
# Mesajlar
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["GET", "POST"])
def api_mesajlar(request, genel_id):
    grup = _grubu_getir(request, genel_id)

    if request.method == "GET":
        sorgu = Mesaj.objects.filter(grup=grup, silindi=False).select_related("gonderen")

        sonra = request.GET.get("sonra")
        if sonra:
            try:
                sorgu = sorgu.filter(pk__gt=int(sonra))
            except ValueError:
                return _hata("Geçersiz 'sonra' değeri.")
            kayitlar = list(sorgu.order_by("olusturulma")[: settings.MESSAGES_PAGE_SIZE])
        else:
            # İlk yükleme: en yeni sayfa, sonra kronolojiye çevir.
            kayitlar = list(
                sorgu.order_by("-olusturulma")[: settings.MESSAGES_PAGE_SIZE]
            )
            kayitlar.reverse()

        return JsonResponse(
            {
                "tamam": True,
                "mesajlar": [
                    {
                        "id": m.pk,
                        "gonderen_id": m.gonderen_id,
                        "gonderen_ad": m.gonderen.gorunen_ad,
                        "anahtar_surum": m.anahtar_surum,
                        "sifreli_metin": m.sifreli_metin,
                        "iv": m.iv,
                        "zaman": m.olusturulma.isoformat(),
                    }
                    for m in kayitlar
                ],
            }
        )

    # POST — mesaj gönder
    if sinir_asildi(f"mesaj:{request.user.pk}", limit=60, saniye=60):
        return _hata("Çok hızlı mesaj gönderiyorsun.", 429)

    try:
        veri = _govde(request)
        anahtar_surum = int(veri.get("anahtar_surum", 0))
        if anahtar_surum < 1:
            raise ValueError("Anahtar sürümü geçersiz.")
        sifreli = _b64_dogrula(
            veri.get("sifreli_metin"), MAX_SIFRELI_UZUNLUK, "Şifreli metin"
        )
        iv = _b64_dogrula(veri.get("iv"), 32, "IV")
    except (ValueError, TypeError) as hata:
        return _hata(str(hata))

    anahtar = aktif_anahtar(grup)
    if anahtar is None or anahtar.surum != anahtar_surum:
        return _hata("Sohbet anahtarı güncel değil. Sayfayı yenile.", 409)

    mesaj = Mesaj.objects.create(
        grup=grup,
        gonderen=request.user,
        anahtar_surum=anahtar_surum,
        sifreli_metin=sifreli,
        iv=iv,
    )
    return JsonResponse(
        {
            "tamam": True,
            "mesaj": {
                "id": mesaj.pk,
                "gonderen_id": mesaj.gonderen_id,
                "gonderen_ad": request.user.gorunen_ad,
                "anahtar_surum": mesaj.anahtar_surum,
                "sifreli_metin": mesaj.sifreli_metin,
                "iv": mesaj.iv,
                "zaman": mesaj.olusturulma.isoformat(),
            },
        }
    )
