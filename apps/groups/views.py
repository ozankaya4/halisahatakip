"""Grup görünümleri: kurma, üye yönetimi, davetler ve katılma onayı."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.ratelimit import sinir_asildi
from apps.notifications.models import Bildirim, bildir, toplu_bildir

from .forms import DavetFormu, GrupFormu, KatilmaFormu
from .models import DavetBagi, Grup, Uyelik
from .yetki import uye_gerekli, yonetici_gerekli


@login_required
def liste(request):
    uyelikler = (
        Uyelik.objects.filter(kullanici=request.user)
        .exclude(durum__in=[Uyelik.Durum.REDDEDILDI, Uyelik.Durum.AYRILDI])
        .select_related("grup")
        .order_by("durum", "grup__ad")
    )
    return render(
        request,
        "groups/liste.html",
        {
            "onayli": [u for u in uyelikler if u.durum == Uyelik.Durum.ONAYLI],
            "bekleyen": [u for u in uyelikler if u.durum == Uyelik.Durum.BEKLIYOR],
        },
    )


@login_required
def olustur(request):
    if request.method == "POST":
        form = GrupFormu(request.POST)
        if form.is_valid():
            with transaction.atomic():
                grup = form.save(commit=False)
                grup.kurucu = request.user
                grup.save()
                # Kurucu doğrudan onaylı yönetici olur.
                Uyelik.objects.create(
                    grup=grup,
                    kullanici=request.user,
                    rol=Uyelik.Rol.YONETICI,
                    durum=Uyelik.Durum.ONAYLI,
                    onaylayan=request.user,
                    karar_tarihi=timezone.now(),
                )
            messages.success(
                request, f"“{grup.ad}” kuruldu. Şimdi arkadaşlarını davet edebilirsin."
            )
            return redirect("groups:davetler", genel_id=grup.genel_id)
    else:
        form = GrupFormu()
    return render(request, "groups/olustur.html", {"form": form})


@uye_gerekli
def detay(request, grup):
    from apps.matches.models import Mac

    simdi = timezone.now()
    yaklasan = (
        Mac.objects.filter(grup=grup, baslangic__gte=simdi)
        .order_by("baslangic")
        .prefetch_related("katilimlar")[:5]
    )
    gecmis = Mac.objects.filter(grup=grup, baslangic__lt=simdi).order_by("-baslangic")[:5]

    # Sıralama yalnızca BU grupta oynanan maçların puanlarından hesaplanır.
    # Eskiden profildeki küresel ortalamaya bakılıyordu; o hâliyle biri kendi
    # grubunu kurup kendine 10 vererek buradaki sıralamayı da yükseltebiliyordu.
    from apps.ratings.gorunurluk import gizli_mac_idleri
    from apps.ratings.hesaplar import grup_siralamasi

    en_iyiler = grup_siralamasi(grup, limit=5, izleyen=request.user)
    # Puanlaması tamamlanmadığı için sıralamaya girmeyen maç adedi.
    gizli_mac_sayisi = len(gizli_mac_idleri(grup, request.user))

    # Şüpheli oylama nedeniyle karantinaya alınmış, yönetici kararı bekleyen
    # kayıt var mı? Sayfada uyarı olarak gösteriliyor.
    bekleyen_oy_incelemesi = 0
    bekleyen_sikayet = 0
    if grup.yonetici_mi(request.user):
        from apps.moderation.models import Sikayet
        from apps.ratings.models import Puan

        bekleyen_oy_incelemesi = (
            Puan.objects.filter(karantinada=True, mac__grup=grup)
            .values("mac_id", "puanlayan_id")
            .distinct()
            .count()
        )
        bekleyen_sikayet = Sikayet.objects.filter(
            grup=grup, durum=Sikayet.Durum.BEKLIYOR
        ).count()

    return render(
        request,
        "groups/detay.html",
        {
            "grup": grup,
            "yonetici_mi": grup.yonetici_mi(request.user),
            "yaklasan_maclar": yaklasan,
            "gecmis_maclar": gecmis,
            "en_iyiler": en_iyiler,
            "gizli_mac_sayisi": gizli_mac_sayisi,
            "bekleyen_sayisi": grup.bekleyen_sayisi,
            "bekleyen_oy_incelemesi": bekleyen_oy_incelemesi,
            "bekleyen_sikayet": bekleyen_sikayet,
        },
    )


@yonetici_gerekli
def duzenle(request, grup):
    if request.method == "POST":
        form = GrupFormu(request.POST, instance=grup)
        if form.is_valid():
            form.save()
            messages.success(request, "Grup bilgileri güncellendi.")
            return redirect("groups:detay", genel_id=grup.genel_id)
    else:
        form = GrupFormu(instance=grup)
    return render(request, "groups/duzenle.html", {"form": form, "grup": grup})


@uye_gerekli
def uyeler(request, grup):
    yonetici_mi = grup.yonetici_mi(request.user)
    onayli = grup.onayli_uyelikler.order_by("-rol", "kullanici__ad_soyad")
    bekleyen = (
        grup.uyelikler.filter(durum=Uyelik.Durum.BEKLIYOR).select_related("kullanici")
        if yonetici_mi
        else []
    )
    return render(
        request,
        "groups/uyeler.html",
        {
            "grup": grup,
            "yonetici_mi": yonetici_mi,
            "onayli_uyelikler": onayli,
            "bekleyen_uyelikler": bekleyen,
            "benim_uyeligim": grup.uyelik(request.user),
        },
    )


# ---------------------------------------------------------------------------
# Davet bağlantıları
# ---------------------------------------------------------------------------
@yonetici_gerekli
def davetler(request, grup):
    yeni_bag = None

    if request.method == "POST":
        form = DavetFormu(request.POST)
        if form.is_valid():
            kayit, ham_jeton = DavetBagi.olustur(
                grup=grup,
                olusturan=request.user,
                gun=form.cleaned_data["gun"],
                max_kullanim=form.cleaned_data["max_kullanim"],
                etiket=form.cleaned_data["etiket"],
            )
            # Ham jeton yalnızca burada, bir kez gösterilir; DB'de özeti var.
            #
            # Jeton adresin # işaretinden SONRA duruyor. Tarayıcı bu parçayı
            # sunucuya hiç göndermiyor, dolayısıyla erişim günlüklerine de
            # girmiyor. Yolun içinde taşındığı sürece, veritabanında yalnızca
            # özetini saklamanın anlamı kalmıyordu: günlüğü okuyan çalışan bir
            # davet bağlantısı elde ediyordu.
            yeni_bag = (
                request.build_absolute_uri(reverse("groups:davet_ile_katil"))
                + "#"
                + ham_jeton
            )
            messages.success(
                request,
                "Davet bağlantısı oluşturuldu. Bağlantıyı şimdi kopyala; "
                "bu sayfadan ayrıldıktan sonra bir daha gösterilemez.",
            )
            form = DavetFormu()
    else:
        form = DavetFormu()

    return render(
        request,
        "groups/davetler.html",
        {
            "grup": grup,
            "form": form,
            "yeni_bag": yeni_bag,
            "davetler": grup.davetler.select_related("olusturan"),
        },
    )


@yonetici_gerekli
@require_POST
def davet_iptal(request, grup, davet_id: int):
    davet = get_object_or_404(DavetBagi, pk=davet_id, grup=grup)
    davet.iptal_edildi = True
    davet.save(update_fields=["iptal_edildi", "guncellenme"])
    messages.info(request, "Davet bağlantısı iptal edildi.")
    return redirect("groups:davetler", genel_id=grup.genel_id)


@login_required
def davet_ile_katil(request):
    """
    Davet bağlantısının açılış sayfası.

    Bağlantı kişiyi doğrudan üye yapmaz: üyelik "onay bekliyor" durumunda
    açılır ve yöneticilere bildirim gider. Onay olmadan grup içeriği görünmez.

    JETON URL YOLUNDA DEĞİL. Adresin # işaretinden sonraki parçasında geliyor;
    tarayıcı bu parçayı sunucuya hiç göndermiyor. static/js/davet.js onu okuyup
    gizli alana yazıyor ve sayfa POST ediyor, yani jeton sunucuya yalnızca
    istek GÖVDESİNDE ulaşıyor. Gövde ne nginx ne gunicorn erişim günlüğüne
    yazılıyor.

    Betik çalışmazsa sayfa kullanıcıdan kodu elle yapıştırmasını istiyor;
    kod zaten adres çubuğunda duruyor.
    """
    jeton = (request.POST.get("jeton") or "").strip()

    # GET: henüz jeton yok. Sayfa açılıyor, betik jetonu yerleştirip
    # gönderiyor. Jetonsuz POST da (betik yok, alan boş) buraya düşüyor.
    if not jeton:
        return render(request, "groups/davet_kod_iste.html", status=200)

    davet = DavetBagi.jetondan_bul(jeton)
    if davet is None or not davet.gecerli_mi:
        return render(request, "groups/davet_gecersiz.html", status=404)

    grup = davet.grup
    mevcut = grup.uyelik(request.user)

    if mevcut and mevcut.durum == Uyelik.Durum.ONAYLI:
        messages.info(request, "Bu grubun zaten üyesisin.")
        return redirect("groups:detay", genel_id=grup.genel_id)
    if mevcut and mevcut.durum == Uyelik.Durum.BEKLIYOR:
        return render(request, "groups/katilma_beklemede.html", {"grup": grup})

    # Jeton geçerli ama kullanıcı henüz "katıl" demedi: önizlemeyi göster.
    # Katılma isteği ancak formda "onayla" alanı geldiğinde oluşuyor, yoksa
    # bağlantıya tıklamak tek başına istek göndermiş sayılırdı.
    if not request.POST.get("onayla"):
        return render(
            request,
            "groups/davet_kabul.html",
            {"grup": grup, "form": KatilmaFormu(), "jeton": jeton},
        )

    if request.method == "POST":
        form = KatilmaFormu(request.POST)
        if sinir_asildi(f"katil:{request.user.pk}", limit=10, saniye=3600):
            messages.error(
                request, "Çok fazla katılma isteği gönderdin. Biraz sonra tekrar dene."
            )
            return redirect("core:dashboard")

        if form.is_valid():
            with transaction.atomic():
                # Hak ÖNCE alınıyor, üyelik sonra açılıyor.
                #
                # Sıra önemli: kullanım hakkı kalmadıysa hiçbir şey
                # yaratmadan çıkıyoruz. Ters sırada, hakkı bitmiş bir
                # bağlantıyla üyelik açılıp sayaç artmamış olurdu.
                if not davet.kullanildi():
                    return render(
                        request, "groups/davet_gecersiz.html", status=404
                    )

                if mevcut:
                    # Daha önce reddedilmiş/ayrılmış: aynı kaydı yeniden aç.
                    mevcut.durum = Uyelik.Durum.BEKLIYOR
                    mevcut.rol = Uyelik.Rol.UYE
                    mevcut.katilma_notu = form.cleaned_data["katilma_notu"]
                    mevcut.onaylayan = None
                    mevcut.karar_tarihi = None
                    mevcut.save()
                    uyelik = mevcut
                else:
                    uyelik = Uyelik.objects.create(
                        grup=grup,
                        kullanici=request.user,
                        durum=Uyelik.Durum.BEKLIYOR,
                        katilma_notu=form.cleaned_data["katilma_notu"],
                    )

                yoneticiler = [
                    u.kullanici
                    for u in grup.uyelikler.filter(
                        durum=Uyelik.Durum.ONAYLI, rol=Uyelik.Rol.YONETICI
                    ).select_related("kullanici")
                ]
                toplu_bildir(
                    yoneticiler,
                    Bildirim.Tur.KATILMA_ISTEGI,
                    f"{request.user.gorunen_ad} gruba katılmak istiyor",
                    f"“{grup.ad}” için yeni katılma isteği.",
                    reverse("groups:uyeler", kwargs={"genel_id": grup.genel_id}),
                )
            return render(request, "groups/katilma_beklemede.html", {"grup": grup})
    else:
        form = KatilmaFormu()

    # Form geçersizse önizlemeye dön; jeton gizli alanda taşınmaya devam etsin.
    return render(
        request,
        "groups/davet_kabul.html",
        {"grup": grup, "form": form, "jeton": jeton},
    )


# ---------------------------------------------------------------------------
# Üyelik kararları
# ---------------------------------------------------------------------------
@yonetici_gerekli
@require_POST
def istek_karari(request, grup, uyelik_id: int):
    uyelik = get_object_or_404(
        Uyelik.objects.select_related("kullanici"),
        pk=uyelik_id,
        grup=grup,
        durum=Uyelik.Durum.BEKLIYOR,
    )
    karar = request.POST.get("karar")

    if karar == "onayla":
        uyelik.onayla(request.user)
        bildir(
            uyelik.kullanici,
            Bildirim.Tur.KATILMA_ONAYLANDI,
            f"“{grup.ad}” grubuna kabul edildin",
            "Artık maçları ve sohbeti görebilirsin.",
            reverse("groups:detay", kwargs={"genel_id": grup.genel_id}),
        )
        messages.success(request, f"{uyelik.kullanici.gorunen_ad} gruba eklendi.")
    elif karar == "reddet":
        uyelik.reddet(request.user)
        bildir(
            uyelik.kullanici,
            Bildirim.Tur.KATILMA_REDDEDILDI,
            f"“{grup.ad}” katılma isteğin onaylanmadı",
            "",
            reverse("groups:liste"),
        )
        messages.info(request, "İstek reddedildi.")
    else:
        messages.error(request, "Geçersiz işlem.")

    return redirect("groups:uyeler", genel_id=grup.genel_id)


@yonetici_gerekli
@require_POST
def rol_degistir(request, grup, uyelik_id: int):
    uyelik = get_object_or_404(
        Uyelik.objects.select_related("kullanici"),
        pk=uyelik_id,
        grup=grup,
        durum=Uyelik.Durum.ONAYLI,
    )
    yeni_rol = request.POST.get("rol")
    if yeni_rol not in {Uyelik.Rol.UYE, Uyelik.Rol.YONETICI}:
        messages.error(request, "Geçersiz rol.")
        return redirect("groups:uyeler", genel_id=grup.genel_id)

    # Grubun yöneticisiz kalmasını engelle.
    if (
        yeni_rol == Uyelik.Rol.UYE
        and uyelik.rol == Uyelik.Rol.YONETICI
        and grup.yonetici_sayisi <= 1
    ):
        messages.error(request, "Grubun en az bir yöneticisi kalmalı.")
        return redirect("groups:uyeler", genel_id=grup.genel_id)

    # Kurucuyu yalnızca nihai yönetici indirebilir.
    if (
        yeni_rol == Uyelik.Rol.UYE
        and uyelik.kullanici_id == grup.kurucu_id
        and not request.user.is_superuser
    ):
        messages.error(request, "Grubun kurucusunun yöneticiliği kaldırılamaz.")
        return redirect("groups:uyeler", genel_id=grup.genel_id)

    onceki = uyelik.rol
    uyelik.rol = yeni_rol
    uyelik.save(update_fields=["rol", "guncellenme"])

    if yeni_rol == Uyelik.Rol.YONETICI and onceki != yeni_rol:
        bildir(
            uyelik.kullanici,
            Bildirim.Tur.YONETICI_YAPILDI,
            f"“{grup.ad}” grubunda yönetici oldun",
            "Artık maç ekleyebilir ve üye isteklerini onaylayabilirsin.",
            reverse("groups:detay", kwargs={"genel_id": grup.genel_id}),
        )
    messages.success(request, f"{uyelik.kullanici.gorunen_ad} · rol güncellendi.")
    return redirect("groups:uyeler", genel_id=grup.genel_id)


@yonetici_gerekli
@require_POST
def uye_cikar(request, grup, uyelik_id: int):
    uyelik = get_object_or_404(
        Uyelik.objects.select_related("kullanici"),
        pk=uyelik_id,
        grup=grup,
        durum=Uyelik.Durum.ONAYLI,
    )

    if uyelik.kullanici_id == request.user.pk:
        messages.error(request, "Kendini çıkaramazsın; “Gruptan ayrıl” seçeneğini kullan.")
        return redirect("groups:uyeler", genel_id=grup.genel_id)
    if uyelik.kullanici_id == grup.kurucu_id and not request.user.is_superuser:
        messages.error(request, "Grubun kurucusu çıkarılamaz.")
        return redirect("groups:uyeler", genel_id=grup.genel_id)

    cikarilan = uyelik.kullanici
    with transaction.atomic():
        uyelik.durum = Uyelik.Durum.AYRILDI
        uyelik.rol = Uyelik.Rol.UYE
        uyelik.karar_tarihi = timezone.now()
        uyelik.save(update_fields=["durum", "rol", "karar_tarihi", "guncellenme"])
        _uyelik_degisti(grup, cikarilan)

    bildir(
        cikarilan,
        Bildirim.Tur.GRUPTAN_CIKARILDI,
        f"“{grup.ad}” grubundan çıkarıldın",
        "",
        reverse("groups:liste"),
    )
    messages.info(request, f"{cikarilan.gorunen_ad} gruptan çıkarıldı.")
    return redirect("groups:uyeler", genel_id=grup.genel_id)


@uye_gerekli
@require_POST
def ayril(request, grup):
    uyelik = grup.uyelik(request.user)
    if uyelik is None:
        return redirect("groups:liste")

    if uyelik.yonetici_mi and grup.yonetici_sayisi <= 1 and grup.uye_sayisi > 1:
        messages.error(
            request,
            "Tek yönetici sensin. Ayrılmadan önce başka birini yönetici yapmalısın.",
        )
        return redirect("groups:uyeler", genel_id=grup.genel_id)

    with transaction.atomic():
        uyelik.durum = Uyelik.Durum.AYRILDI
        uyelik.rol = Uyelik.Rol.UYE
        uyelik.karar_tarihi = timezone.now()
        uyelik.save(update_fields=["durum", "rol", "karar_tarihi", "guncellenme"])
        _uyelik_degisti(grup, request.user)

    messages.info(request, f"“{grup.ad}” grubundan ayrıldın.")
    return redirect("groups:liste")


def _uyelik_degisti(grup, ayrilan) -> None:
    """
    Biri gruptan çıktığında sohbet anahtarını döndürür.

    Ayrılan kişi eski anahtarı zaten görmüştü; bunu geri alamayız. Ama
    anahtarı çevirerek **bundan sonraki** mesajları okuyamamasını sağlarız
    (ileri yönlü gizlilik).
    """
    from apps.chat.services import anahtari_dondur

    anahtari_dondur(grup, ayrilan_kullanici=ayrilan)


@uye_gerekli
def uye_istatistik(request, grup, kullanici_id: int):
    """
    Bir oyuncunun bu gruptaki istatistikleri.

    @uye_gerekli ile korunuyor: bir grubun istatistikleri o grubun üyelerine
    özel. Ayrıca hedef kişinin de aynı grupta ONAYLI üye olması aranıyor;
    aksi hâlde grup dışından rastgele bir kullanıcı kimliği verip
    istatistik sayfası açılabilirdi.
    """
    from apps.groups.istatistik import uye_istatistikleri

    uyelik = get_object_or_404(
        Uyelik.objects.select_related("kullanici", "kullanici__profil"),
        grup=grup,
        kullanici_id=kullanici_id,
        durum=Uyelik.Durum.ONAYLI,
    )

    return render(
        request,
        "groups/uye_istatistik.html",
        {
            "grup": grup,
            "uyelik": uyelik,
            "gosterilen": uyelik.kullanici,
            "istatistik": uye_istatistikleri(
                grup, uyelik.kullanici, izleyen=request.user
            ),
            "yonetici_mi": grup.yonetici_mi(request.user),
        },
    )
