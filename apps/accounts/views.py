from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ProfilFormu
from .models import Profil, User


@login_required
def profil_duzenle(request):
    profil, _ = Profil.objects.get_or_create(kullanici=request.user)

    if request.method == "POST":
        form = ProfilFormu(request.POST, request.FILES, instance=profil)
        if form.is_valid():
            form.save()
            messages.success(request, "Profilin güncellendi.")
            return redirect("accounts:profil", kullanici_id=request.user.pk)
    else:
        form = ProfilFormu(instance=profil)

    return render(request, "accounts/profil_duzenle.html", {"form": form, "profil": profil})


def profil(request, kullanici_id: int):
    """
    Oyuncu profili.

    PUBLIC_PROFILES kapalıyken (varsayılan) yalnızca giriş yapmış kullanıcılar
    görebilir. Tek tek puanlar hiçbir koşulda gösterilmez; yalnızca ortalama.
    """
    if not request.user.is_authenticated and not settings.PUBLIC_PROFILES:
        raise Http404("Bulunamadı.")

    kullanici = get_object_or_404(
        User.objects.select_related("profil"), pk=kullanici_id, is_active=True
    )
    profil_kaydi, _ = Profil.objects.get_or_create(kullanici=kullanici)

    # Grup bazlı ortalamalar yalnızca istekte bulunanın da üyesi olduğu
    # gruplar için gösterilir; başka grupların oyuncu listesi sızmasın.
    grup_ozetleri = []
    if request.user.is_authenticated:
        from apps.groups.models import Uyelik
        from apps.ratings.models import Puan

        if request.user.is_superuser:
            gorulebilir_grup_idleri = list(
                Uyelik.objects.filter(
                    kullanici=kullanici, durum=Uyelik.Durum.ONAYLI
                ).values_list("grup_id", flat=True)
            )
        else:
            benim = set(
                Uyelik.objects.filter(
                    kullanici=request.user, durum=Uyelik.Durum.ONAYLI
                ).values_list("grup_id", flat=True)
            )
            onun = set(
                Uyelik.objects.filter(
                    kullanici=kullanici, durum=Uyelik.Durum.ONAYLI
                ).values_list("grup_id", flat=True)
            )
            gorulebilir_grup_idleri = list(benim & onun)

        if gorulebilir_grup_idleri:
            grup_ozetleri = (
                Puan.objects.filter(
                    puanlanan=kullanici, mac__grup_id__in=gorulebilir_grup_idleri
                )
                .values("mac__grup__ad", "mac__grup__id")
                .annotate(ortalama=Avg("deger"), adet=Count("id"))
                .order_by("-ortalama")
            )

    return render(
        request,
        "accounts/profil.html",
        {
            "gosterilen": kullanici,
            "profil": profil_kaydi,
            "grup_ozetleri": grup_ozetleri,
            "kendi_profili": request.user.is_authenticated
            and request.user.pk == kullanici.pk,
            "esik": settings.RATING_MIN_VOTES_TO_DISPLAY,
        },
    )
