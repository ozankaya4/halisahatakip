"""Maç görünümleri: takvim, yoklama anketi, kadro ve fotoğraflar."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.ratelimit import sinir_asildi
from apps.groups.models import Uyelik
from apps.groups.yetki import uye_gerekli, yonetici_gerekli
from apps.notifications.models import Bildirim, toplu_bildir
from apps.ratings.denetim import macin_adami
from apps.ratings.hesaplar import mac_puanlarini_sil

from .dizilim import dizilim_verisi
from .forms import FotografFormu, MacFormu
from .models import Katilim, Mac, MacFotografi

# Bir maça yüklenebilecek azami fotoğraf sayısı.
MAC_BASINA_FOTO_SINIRI = 60


def _mac_getir(request, mac_id: int, yonetici_sart: bool = False) -> Mac:
    """Maçı getirir ve isteyenin o gruba erişim yetkisini doğrular."""
    mac = get_object_or_404(Mac.objects.select_related("grup"), pk=mac_id)
    if yonetici_sart:
        if not mac.grup.yonetici_mi(request.user):
            raise PermissionDenied("Bu işlem için grup yöneticisi olmalısınız.")
    else:
        if not (request.user.is_superuser or mac.grup.uye_mi(request.user)):
            raise PermissionDenied("Bu grubun üyesi değilsiniz.")
    return mac


@uye_gerekli
def liste(request, grup):
    simdi = timezone.now()
    return render(
        request,
        "matches/liste.html",
        {
            "grup": grup,
            "yonetici_mi": grup.yonetici_mi(request.user),
            "yaklasan": Mac.objects.filter(grup=grup, baslangic__gte=simdi).order_by(
                "baslangic"
            ),
            "gecmis": Mac.objects.filter(grup=grup, baslangic__lt=simdi).order_by(
                "-baslangic"
            )[:30],
        },
    )


@yonetici_gerekli
def olustur(request, grup):
    if request.method == "POST":
        form = MacFormu(request.POST)
        if form.is_valid():
            with transaction.atomic():
                mac = form.save(commit=False)
                mac.grup = grup
                mac.olusturan = request.user
                mac.save()

                alicilar = [
                    u.kullanici
                    for u in grup.onayli_uyelikler
                    if u.kullanici_id != request.user.pk
                ]
                yerel = timezone.localtime(mac.baslangic)
                toplu_bildir(
                    alicilar,
                    Bildirim.Tur.YENI_MAC,
                    f"“{grup.ad}” için yeni maç",
                    f"{yerel:%d.%m.%Y %H:%M}"
                    + (f" · {mac.konum}" if mac.konum else "")
                    + (" · Yoklama açık" if mac.yoklama_acik else ""),
                    reverse("matches:detay", kwargs={"mac_id": mac.pk}),
                )
            messages.success(request, "Maç eklendi ve gruba bildirildi.")
            return redirect("matches:detay", mac_id=mac.pk)
    else:
        form = MacFormu()
    return render(request, "matches/olustur.html", {"form": form, "grup": grup})


@login_required
def detay(request, mac_id: int):
    mac = _mac_getir(request, mac_id)
    grup = mac.grup

    katilimlar = list(
        mac.katilimlar.select_related("kullanici", "kullanici__profil").all()
    )
    yanit_haritasi = {k.kullanici_id: k for k in katilimlar}

    uyelikler = list(grup.onayli_uyelikler)
    satirlar = [
        {"kullanici": u.kullanici, "katilim": yanit_haritasi.get(u.kullanici_id)}
        for u in uyelikler
    ]
    sirala = {"geliyorum": 0, "belki": 1, "yokum": 2, None: 3}
    satirlar.sort(
        key=lambda s: (
            sirala.get(s["katilim"].yanit if s["katilim"] else None, 3),
            s["kullanici"].gorunen_ad.lower(),
        )
    )

    benim_katilimim = yanit_haritasi.get(request.user.pk)
    sayim = mac.sayim()
    toplam_uye = max(grup.uye_sayisi, 1)

    # Takım kadroları ve maçın adamı yalnızca maç oynandıysa anlamlı.
    adamlar = macin_adami(mac) if mac.gecmis_mi else []
    adam_idleri = {a["kullanici"].pk for a in adamlar}

    takimlar = []
    if mac.takimlar_kurulmus_mu:
        for kod, ad in Mac.Takim.choices:
            takimlar.append(
                {
                    "kod": kod,
                    "ad": ad,
                    "oyuncular": [
                        {
                            "kullanici": k.kullanici,
                            "macin_adami": k.kullanici_id in adam_idleri,
                        }
                        for k in mac.takim_katilimlari(kod)
                    ],
                    "skor": mac.skor_a if kod == Mac.Takim.A else mac.skor_b,
                    "kazandi": mac.kazanan_takim == kod,
                }
            )

    return render(
        request,
        "matches/detay.html",
        {
            "mac": mac,
            "grup": grup,
            "yonetici_mi": grup.yonetici_mi(request.user),
            "satirlar": satirlar,
            "benim_katilimim": benim_katilimim,
            "sayim": sayim,
            "geliyorum_yuzde": round(sayim["geliyorum"] * 100 / toplam_uye),
            "fotograflar": mac.fotograflar.all(),
            "foto_siniri": MAC_BASINA_FOTO_SINIRI,
            "puanlayabilir": mac.kullanici_puanlayabilir(request.user),
            "foto_formu": FotografFormu(),
            "takimlar": takimlar,
            "macin_adamlari": adamlar,
        },
    )


@login_required
def duzenle(request, mac_id: int):
    mac = _mac_getir(request, mac_id, yonetici_sart=True)
    if request.method == "POST":
        form = MacFormu(request.POST, instance=mac)
        if form.is_valid():
            form.save()
            alicilar = [
                u.kullanici
                for u in mac.grup.onayli_uyelikler
                if u.kullanici_id != request.user.pk
            ]
            yerel = timezone.localtime(mac.baslangic)
            toplu_bildir(
                alicilar,
                Bildirim.Tur.MAC_GUNCELLENDI,
                f"“{mac.grup.ad}” maçı güncellendi",
                f"Yeni bilgi: {yerel:%d.%m.%Y %H:%M}"
                + (f" · {mac.konum}" if mac.konum else ""),
                reverse("matches:detay", kwargs={"mac_id": mac.pk}),
            )
            messages.success(request, "Maç güncellendi.")
            return redirect("matches:detay", mac_id=mac.pk)
    else:
        form = MacFormu(instance=mac)
    return render(request, "matches/duzenle.html", {"form": form, "mac": mac, "grup": mac.grup})


@login_required
@require_POST
def iptal_durumu(request, mac_id: int):
    mac = _mac_getir(request, mac_id, yonetici_sart=True)
    mac.iptal = not mac.iptal
    mac.save(update_fields=["iptal", "guncellenme"])

    if mac.iptal:
        # İptal edilen maçın puanları silinir. Aksi hâlde oynanmamış bir maç
        # üzerinden puan biriktirmek mümkün olurdu: maçı kur, puanları al,
        # sonra iptal et. Puanlar gittiği için ortalamalar da düzeliyor.
        silinen = mac_puanlarini_sil(mac)

        alicilar = [
            u.kullanici
            for u in mac.grup.onayli_uyelikler
            if u.kullanici_id != request.user.pk
        ]
        yerel = timezone.localtime(mac.baslangic)
        toplu_bildir(
            alicilar,
            Bildirim.Tur.MAC_IPTAL,
            f"“{mac.grup.ad}” maçı iptal edildi",
            f"{yerel:%d.%m.%Y %H:%M}",
            reverse("matches:detay", kwargs={"mac_id": mac.pk}),
        )
        if silinen:
            messages.info(
                request,
                f"Maç iptal edildi ve gruba bildirildi. "
                f"Bu maça verilen {silinen} puan da silindi.",
            )
        else:
            messages.info(request, "Maç iptal edildi ve gruba bildirildi.")
    else:
        messages.success(
            request,
            "Maç yeniden aktif edildi. İptal sırasında silinen puanlar geri gelmez; "
            "puanlama süresi hâlâ açıksa yeniden verilebilir.",
        )
    return redirect("matches:detay", mac_id=mac.pk)


@login_required
@require_POST
def sil(request, mac_id: int):
    """
    Maçı tamamen siler.

    Yalnızca grup yöneticisi ve yalnızca **henüz oynanmamış** maçlar için.
    Oynanmış bir maçın silinmesine izin verilmiyor: o maçın puanları,
    kadrosu ve fotoğrafları grubun geçmiş kaydı; yanlışlıkla ya da işine
    gelmediği için silinebilmemeli. Oynanmış maçlar yerine "İptal et"
    kullanılır, o da puanları temizler ama kaydı bırakır.
    """
    mac = _mac_getir(request, mac_id, yonetici_sart=True)

    if mac.gecmis_mi:
        messages.error(
            request,
            "Oynanmış bir maç silinemez. Geçmiş kayıt olarak kalır; "
            "istersen “İptal et” diyebilirsin, bu maça verilen puanlar silinir.",
        )
        return redirect("matches:detay", mac_id=mac.pk)

    grup_id = mac.grup.genel_id

    # Puanları önce açıkça siliyoruz: veritabanı zaten CASCADE ile silerdi
    # ama toplu silme model delete()'ini çağırmadığı için profil sayaçları
    # eski değerde takılı kalırdı.
    mac_puanlarini_sil(mac)

    # Fotoğraf dosyaları diskte yetim kalmasın diye tek tek siliyoruz;
    # CASCADE yalnızca satırları siler, dosyalara dokunmaz.
    for foto in mac.fotograflar.all():
        foto.delete()

    mac.delete()
    messages.info(request, "Maç silindi.")
    return redirect("matches:liste", genel_id=grup_id)


# ---------------------------------------------------------------------------
# Yoklama anketi
# ---------------------------------------------------------------------------
@login_required
@require_POST
def yoklama_oyu(request, mac_id: int):
    mac = _mac_getir(request, mac_id)

    if not mac.yoklama_alinabilir:
        messages.error(request, "Bu maç için yoklama kapandı.")
        return redirect("matches:detay", mac_id=mac.pk)

    yanit = request.POST.get("yanit")
    if yanit not in Katilim.Yanit.values:
        messages.error(request, "Geçersiz yanıt.")
        return redirect("matches:detay", mac_id=mac.pk)

    if sinir_asildi(f"yoklama:{request.user.pk}:{mac.pk}", limit=20, saniye=300):
        messages.error(request, "Çok sık değişiklik yapıyorsun, biraz bekle.")
        return redirect("matches:detay", mac_id=mac.pk)

    Katilim.objects.update_or_create(
        mac=mac, kullanici=request.user, defaults={"yanit": yanit}
    )
    messages.success(request, "Yanıtın kaydedildi.")
    return redirect("matches:detay", mac_id=mac.pk)


@login_required
@require_POST
def yoklama_durumu(request, mac_id: int):
    """Yöneticinin yoklamayı açıp kapatması."""
    mac = _mac_getir(request, mac_id, yonetici_sart=True)
    mac.yoklama_acik = not mac.yoklama_acik
    mac.save(update_fields=["yoklama_acik", "guncellenme"])

    if mac.yoklama_acik:
        alicilar = [
            u.kullanici
            for u in mac.grup.onayli_uyelikler
            if u.kullanici_id != request.user.pk
        ]
        toplu_bildir(
            alicilar,
            Bildirim.Tur.YOKLAMA_ACILDI,
            f"“{mac.grup.ad}” · yoklama açıldı",
            "Geliyor musun?",
            reverse("matches:detay", kwargs={"mac_id": mac.pk}),
        )
    messages.success(
        request, "Yoklama açıldı." if mac.yoklama_acik else "Yoklama kapatıldı."
    )
    return redirect("matches:detay", mac_id=mac.pk)


@login_required
def kadro_duzenle(request, mac_id: int):
    """
    Maç sonrası gerçek kadronun işaretlenmesi.

    Bu liste puanlama yetkisini belirler: yalnızca burada işaretli oyuncular
    puan verebilir ve puan alabilir.
    """
    mac = _mac_getir(request, mac_id, yonetici_sart=True)
    uyelikler = list(mac.grup.onayli_uyelikler)

    if request.method == "POST":
        secilen = set(request.POST.getlist("oynayan"))
        gecerli_idler = {str(u.kullanici_id) for u in uyelikler}
        secilen &= gecerli_idler  # gruba ait olmayan kimlikleri at

        gecerli_takimlar = {t.value for t in Mac.Takim}

        with transaction.atomic():
            for uyelik in uyelikler:
                oynadi = str(uyelik.kullanici_id) in secilen

                # Takım yalnızca sahaya çıkanlara verilir; oynamayanın
                # takımı temizlenir ki eski atama ortalıkta kalmasın.
                takim = ""
                if oynadi:
                    secim = (request.POST.get(f"takim_{uyelik.kullanici_id}") or "").strip()
                    if secim in gecerli_takimlar:
                        takim = secim

                Katilim.objects.update_or_create(
                    mac=mac,
                    kullanici=uyelik.kullanici,
                    defaults={"katildi": oynadi, "takim": takim},
                    create_defaults={
                        "katildi": oynadi,
                        "takim": takim,
                        "yanit": (
                            Katilim.Yanit.GELIYORUM if oynadi else Katilim.Yanit.YOKUM
                        ),
                    },
                )

            # --- Skor ---------------------------------------------------
            # İkisi de boşsa skor girilmemiş sayılır (0-0 geçerli sonuç
            # olduğu için "boş" ile "sıfır" ayrı tutuluyor).
            ham_a = (request.POST.get("skor_a") or "").strip()
            ham_b = (request.POST.get("skor_b") or "").strip()
            if ham_a == "" and ham_b == "":
                mac.skor_a = mac.skor_b = None
            else:
                try:
                    mac.skor_a = max(0, min(99, int(ham_a or 0)))
                    mac.skor_b = max(0, min(99, int(ham_b or 0)))
                except ValueError:
                    messages.error(request, "Skor sayı olmalı; skor kaydedilmedi.")
                    mac.skor_a = mac.skor_b = None
            mac.save(update_fields=["skor_a", "skor_b", "guncellenme"])

        messages.success(request, "Kadro ve sonuç kaydedildi.")
        return redirect("matches:detay", mac_id=mac.pk)

    mevcut = {k.kullanici_id: k for k in mac.katilimlar.all()}
    satirlar = [
        {
            "kullanici": u.kullanici,
            "isaretli": (
                mevcut[u.kullanici_id].oynadi_mi if u.kullanici_id in mevcut else False
            ),
            "takim": mevcut[u.kullanici_id].takim if u.kullanici_id in mevcut else "",
            "yanit": (
                mevcut[u.kullanici_id].get_yanit_display()
                if u.kullanici_id in mevcut
                else "Yanıt yok"
            ),
        }
        for u in uyelikler
    ]
    return render(
        request,
        "matches/kadro.html",
        {
            "mac": mac,
            "grup": mac.grup,
            "satirlar": satirlar,
            "takimlar": Mac.Takim.choices,
        },
    )


# ---------------------------------------------------------------------------
# Fotoğraflar
# ---------------------------------------------------------------------------
@login_required
@require_POST
def fotograf_yukle(request, mac_id: int):
    mac = _mac_getir(request, mac_id, yonetici_sart=True)

    if sinir_asildi(f"foto:{request.user.pk}", limit=60, saniye=3600):
        messages.error(request, "Yükleme sınırına takıldın, biraz sonra tekrar dene.")
        return redirect("matches:detay", mac_id=mac.pk)

    form = FotografFormu(request.POST, request.FILES)
    dosyalar = request.FILES.getlist("dosyalar")

    if not dosyalar:
        messages.error(request, "Dosya seçilmedi.")
        return redirect("matches:detay", mac_id=mac.pk)

    mevcut_sayi = mac.fotograflar.count()
    if mevcut_sayi + len(dosyalar) > MAC_BASINA_FOTO_SINIRI:
        messages.error(
            request,
            f"Bir maça en fazla {MAC_BASINA_FOTO_SINIRI} fotoğraf yüklenebilir "
            f"(şu an {mevcut_sayi} tane var).",
        )
        return redirect("matches:detay", mac_id=mac.pk)

    aciklama = ""
    if form.is_valid():
        aciklama = form.cleaned_data.get("aciklama", "")

    try:
        temiz_gorseller = FotografFormu().temiz_gorseller(dosyalar)
    except ValidationError as hata:
        messages.error(request, " ".join(hata.messages))
        return redirect("matches:detay", mac_id=mac.pk)

    with transaction.atomic():
        for icerik in temiz_gorseller:
            foto = MacFotografi(mac=mac, yukleyen=request.user, aciklama=aciklama[:120])
            foto.dosya.save(icerik.name, icerik, save=False)
            foto.save()

    messages.success(request, f"{len(temiz_gorseller)} fotoğraf yüklendi.")
    return redirect("matches:detay", mac_id=mac.pk)


@login_required
@require_POST
def fotograf_sil(request, foto_id: int):
    foto = get_object_or_404(
        MacFotografi.objects.select_related("mac", "mac__grup"), pk=foto_id
    )
    grup = foto.mac.grup
    # Yönetici her fotoğrafı, üye yalnızca kendi yüklediğini silebilir.
    if not (grup.yonetici_mi(request.user) or foto.yukleyen_id == request.user.pk):
        raise PermissionDenied("Bu fotoğrafı silme yetkin yok.")

    mac_id = foto.mac_id
    foto.delete()
    messages.info(request, "Fotoğraf silindi.")
    return redirect("matches:detay", mac_id=mac_id)


# ---------------------------------------------------------------------------
# Dizilim (saha görünümü)
# ---------------------------------------------------------------------------
@login_required
def dizilim(request, mac_id: int):
    """
    Maçın saha dizilimi. Maç oynandıktan sonra herkese açık.

    Puanlar maç bazlı: oyuncunun grup ortalaması değil, o maçta aldığı
    ortalama gösteriliyor.
    """
    mac = _mac_getir(request, mac_id)

    if not mac.gecmis_mi:
        messages.info(request, "Dizilim maç oynandıktan sonra görünür.")
        return redirect("matches:detay", mac_id=mac.pk)

    adam_idleri = {a["kullanici"].pk for a in macin_adami(mac)}
    return render(
        request,
        "matches/dizilim.html",
        {
            "mac": mac,
            "grup": mac.grup,
            "takimlar": dizilim_verisi(mac, adam_idleri),
            "yonetici_mi": mac.grup.yonetici_mi(request.user),
            "duzenlenebilir": False,
        },
    )


@login_required
def dizilim_duzenle(request, mac_id: int):
    """
    Dizilim düzenleyici: oyuncular sahada sürüklenerek yerleştirilir.

    Konumlar sahanın yüzdesi olarak geliyor (0-100). Piksel gelseydi farklı
    ekran genişliklerinde dizilim bozulurdu.
    """
    mac = _mac_getir(request, mac_id, yonetici_sart=True)

    if not mac.gecmis_mi:
        messages.info(request, "Dizilim maç oynandıktan sonra düzenlenebilir.")
        return redirect("matches:detay", mac_id=mac.pk)

    if request.method == "POST":
        katilimlar = {
            k.kullanici_id: k
            for k in mac.katilimlar.select_related("kullanici").all()
        }
        guncellenecek = []

        for kullanici_id, katilim in katilimlar.items():
            ham_x = request.POST.get(f"x_{kullanici_id}")
            ham_y = request.POST.get(f"y_{kullanici_id}")
            if ham_x is None or ham_y is None:
                continue
            try:
                # Saha dışına taşan değerleri kırp: bozuk/kötü niyetli
                # gönderim dizilimi bozmasın.
                katilim.poz_x = max(0, min(100, int(float(ham_x))))
                katilim.poz_y = max(0, min(100, int(float(ham_y))))
            except (TypeError, ValueError):
                continue

            katilim.gol = _sayi(request.POST.get(f"gol_{kullanici_id}"), 0, 30)
            katilim.asist = _sayi(request.POST.get(f"asist_{kullanici_id}"), 0, 30)
            katilim.sari_kart = _sayi(request.POST.get(f"sari_{kullanici_id}"), 0, 2)
            katilim.kirmizi_kart = request.POST.get(f"kirmizi_{kullanici_id}") == "1"
            guncellenecek.append(katilim)

        if guncellenecek:
            Katilim.objects.bulk_update(
                guncellenecek,
                ["poz_x", "poz_y", "gol", "asist", "sari_kart", "kirmizi_kart"],
            )
        messages.success(request, "Dizilim kaydedildi.")
        return redirect("matches:dizilim", mac_id=mac.pk)

    adam_idleri = {a["kullanici"].pk for a in macin_adami(mac)}
    return render(
        request,
        "matches/dizilim.html",
        {
            "mac": mac,
            "grup": mac.grup,
            "takimlar": dizilim_verisi(mac, adam_idleri),
            "yonetici_mi": True,
            "duzenlenebilir": True,
        },
    )


def _sayi(ham, en_az: int, en_cok: int) -> int:
    """Formdan gelen sayıyı güvenli aralığa kırpar."""
    try:
        return max(en_az, min(en_cok, int(ham)))
    except (TypeError, ValueError):
        return en_az
