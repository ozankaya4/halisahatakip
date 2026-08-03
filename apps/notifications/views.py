from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Bildirim


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
