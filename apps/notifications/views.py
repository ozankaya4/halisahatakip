import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import Bildirim, PushAbonelik


@login_required
def liste(request):
    sorgu = Bildirim.objects.filter(alici=request.user)
    sayfalar = Paginator(sorgu, 30)
    sayfa = sayfalar.get_page(request.GET.get("sayfa"))
    return render(request, "notifications/liste.html", {"sayfa": sayfa})


@login_required
@require_POST
def okundu_isaretle(request, bildirim_id: int):
    # Sorgu alıcıya kilitli: başkasının bildirimi güncellenemez.
    bildirim = get_object_or_404(Bildirim, pk=bildirim_id, alici=request.user)
    if not bildirim.okundu:
        bildirim.okundu = True
        bildirim.save(update_fields=["okundu"])
    return redirect(bildirim.guvenli_url or "notifications:liste")


@login_required
@require_POST
def hepsini_okundu_isaretle(request):
    Bildirim.objects.filter(alici=request.user, okundu=False).update(okundu=True)
    return redirect("notifications:liste")


# ---------------------------------------------------------------------------
# Web Push abonelikleri
# ---------------------------------------------------------------------------
@login_required
@require_GET
def push_ayarlari(request):
    """
    İstemcinin abone olmak için ihtiyaç duyduğu her şey.

    Açık anahtar gizli değil; tarayıcı aboneliği onunla kuruyor. Anahtar
    tanımlı değilse `acik: false` dönüyor ve arayüz düğmeyi hiç göstermiyor —
    çalışmayan bir düğme göstermektense hiç göstermemek daha dürüst.
    """
    from .push import push_acik_mi

    return JsonResponse(
        {
            "tamam": True,
            "acik": push_acik_mi(),
            "acik_anahtar": settings.VAPID_ACIK_ANAHTAR if push_acik_mi() else "",
            "abone": PushAbonelik.objects.filter(kullanici=request.user).exists(),
        }
    )


@login_required
@require_POST
def push_abone_ol(request):
    """
    Cihazı kaydeder. Aynı uç adres yeniden gelirse kayıt tazeleniyor.

    Aynı kişi birden çok cihazdan abone olabilir; her cihaz ayrı satır.
    `endpoint` benzersiz olduğu için, bir cihaz aboneliğini yenilediğinde
    yeni satır açılmıyor, mevcut satır güncelleniyor.
    """
    try:
        veri = json.loads(request.body.decode("utf-8"))
        endpoint = str(veri["endpoint"])
        anahtarlar = veri["keys"]
        p256dh = str(anahtarlar["p256dh"])
        auth = str(anahtarlar["auth"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return JsonResponse({"tamam": False, "hata": "Geçersiz abonelik."}, status=400)

    if not endpoint.startswith("https://") or len(endpoint) > 2000:
        return JsonResponse({"tamam": False, "hata": "Geçersiz uç adres."}, status=400)
    if len(p256dh) > 255 or len(auth) > 255:
        return JsonResponse({"tamam": False, "hata": "Anahtar çok uzun."}, status=400)

    PushAbonelik.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "kullanici": request.user,
            "p256dh": p256dh,
            "auth": auth,
            "tarayici": (request.META.get("HTTP_USER_AGENT") or "")[:200],
        },
    )
    return JsonResponse({"tamam": True})


@login_required
@require_POST
def push_abonelikten_cik(request):
    """
    Cihazın aboneliğini siler.

    Uç adres verilirse yalnızca o cihaz, verilmezse kullanıcının bütün
    cihazları. İkincisi "artık hiç bildirim istemiyorum" durumu için.
    """
    endpoint = ""
    try:
        endpoint = str(json.loads(request.body.decode("utf-8")).get("endpoint") or "")
    except (ValueError, TypeError, UnicodeDecodeError):
        pass

    sorgu = PushAbonelik.objects.filter(kullanici=request.user)
    if endpoint:
        sorgu = sorgu.filter(endpoint=endpoint)
    silinen, _ = sorgu.delete()
    return JsonResponse({"tamam": True, "silinen": silinen})
