from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
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
    Oyuncu profili: kimlik bilgileri ve oynadığı maç sayısı.

    PUBLIC_PROFILES kapalıyken (varsayılan) yalnızca giriş yapmış kullanıcılar
    görebilir.

    Puan ortalamaları burada GÖSTERİLMEZ. Puanlar yalnızca verildikleri grubun
    içinde anlamlı olduğu için, bir oyuncunun bir gruptaki ortalaması ve
    istatistikleri o grubun üye listesinden açılıyor
    (groups:uye_istatistik). Böylece profil, gruplar üstü nötr bir sayfa
    olarak kalıyor ve hiçbir puan ait olmadığı bağlamda görünmüyor.
    """
    if not request.user.is_authenticated and not settings.PUBLIC_PROFILES:
        raise Http404("Bulunamadı.")

    kullanici = get_object_or_404(
        User.objects.select_related("profil"), pk=kullanici_id, is_active=True
    )
    profil_kaydi, _ = Profil.objects.get_or_create(kullanici=kullanici)

    return render(
        request,
        "accounts/profil.html",
        {
            "gosterilen": kullanici,
            "profil": profil_kaydi,
            "kendi_profili": request.user.is_authenticated
            and request.user.pk == kullanici.pk,
        },
    )
