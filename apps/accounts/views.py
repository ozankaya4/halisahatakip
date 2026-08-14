from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ProfilFormu
from .models import Profil, User


def yoneticisiz_kalacak_gruplar(kullanici):
    """
    Bu kişi silinirse yöneticisiz kalacak, ama içinde başka üye olan gruplar.

    Hesap silmeden önce engel olarak kullanılıyor: son yönetici çekilirse
    grup kilitleniyor, kimse maç ekleyemiyor ya da üye onaylayamıyor.
    Tek başına olduğu grup sorun değil, o grup zaten onunla birlikte
    anlamını yitiriyor.
    """
    from apps.groups.models import Grup, Uyelik

    engeller = []
    uyelikler = Uyelik.objects.filter(
        kullanici=kullanici,
        durum=Uyelik.Durum.ONAYLI,
        rol=Uyelik.Rol.YONETICI,
    ).select_related("grup")

    for uyelik in uyelikler:
        onayli = Uyelik.objects.filter(grup=uyelik.grup, durum=Uyelik.Durum.ONAYLI)
        baska_yonetici = onayli.filter(rol=Uyelik.Rol.YONETICI).exclude(
            kullanici=kullanici
        )
        baska_uye = onayli.exclude(kullanici=kullanici)
        if baska_uye.exists() and not baska_yonetici.exists():
            engeller.append(uyelik.grup)

    return engeller


@login_required
def hesabimi_sil(request):
    """
    Hesabı kalıcı olarak silme.

    Play Store, hesap açtıran uygulamalarda kullanıcıya hesabını silme yolu
    sunulmasını zorunlu tutuyor; bu sayfa olmadan uygulama yayına alınmıyor.

    Silinen: profil, üyelikler, maç katılımları, verilen ve alınan puanlar,
    sohbet anahtarı. Kalan: grubun kendisi, maçlar ve maç fotoğrafları.
    Bunların "oluşturan" alanları SET_NULL, yani bir kişinin ayrılması
    grubun geçmişini silmiyor. Bu ayrım sayfada da açıkça yazıyor.
    """
    engeller = yoneticisiz_kalacak_gruplar(request.user)

    if request.method == "POST":
        if engeller:
            messages.error(
                request,
                "Önce yöneticisi olduğun gruplara başka bir yönetici ata.",
            )
            return redirect("accounts:hesabimi_sil")

        # Yanlışlıkla silmeyi zorlaştırmak için e-postayı yazdırıyoruz;
        # tek bir "Onaylıyorum" kutusu kazara işaretlenebiliyor.
        onay = (request.POST.get("onay") or "").strip().lower()
        if onay != request.user.email.lower():
            messages.error(
                request, "E-posta adresin doğru yazılmadı; hesap silinmedi."
            )
            return redirect("accounts:hesabimi_sil")

        from django.contrib.auth import logout

        silinen = request.user
        logout(request)
        silinen.delete()

        messages.success(
            request, "Hesabın ve sana ait veriler kalıcı olarak silindi."
        )
        return redirect("core:home")

    return render(
        request,
        "accounts/hesabimi_sil.html",
        {"engeller": engeller},
    )


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
