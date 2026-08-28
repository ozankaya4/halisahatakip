"""Maç görünümleri: takvim, yoklama anketi, kadro ve fotoğraflar."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.ratelimit import sinir_asildi
from apps.groups.models import Uyelik
from apps.groups.yetki import uye_gerekli, yonetici_gerekli
from apps.notifications.models import Bildirim, toplu_bildir
from apps.ratings.denetim import macin_adami
from apps.ratings.gorunurluk import puan_gorunurlugu
from apps.ratings.hesaplar import mac_puanlarini_sil

from .dizilim import dizilim_verisi, puanlari_gizle, takim_araligi, x_kirp
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
    #
    # Maçın adamı, adının yanında ortalamasıyla birlikte yazıldığı için
    # doğrudan bir puan sızıntısı; yıldızın kendisi de "en yüksek puan
    # kimde" bilgisini veriyor. Puanlamasını tamamlamamış kişiye ikisi de
    # gösterilmiyor (bkz. apps/ratings/gorunurluk.py).
    durum = puan_gorunurlugu(mac, request.user)
    adamlar = macin_adami(mac) if mac.gecmis_mi and durum.gorebilir else []
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
            "durum": durum,
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
    Maçı tamamen siler. Yalnızca grup yöneticisi.

    Oynanmış maçlar da silinebilir. (Bir dönem yalnızca gelecek maçlara izin
    veriliyordu; yanlış girilen eski maçları temizlemek imkânsız hâle
    geldiği için kaldırıldı.) Silme geri alınamaz ve maçla birlikte
    kadro, puanlar ve fotoğraflar da gider; kaydı korumak isteyen için
    "İptal et" seçeneği duruyor.
    """
    mac = _mac_getir(request, mac_id, yonetici_sart=True)

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
    Kadro, takımlar ve maç sonucu.

    Maçtan ÖNCE de açılabilir: yönetici takımları önceden kurup planlayabilir.
    Maçtan sonra da aynı sayfadan düzeltilir (gelemeyenler, son anda katılanlar)
    ve skor girilir.

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

        mevcut_katilimlar = {k.kullanici_id: k for k in mac.katilimlar.all()}

        with transaction.atomic():
            for uyelik in uyelikler:
                isaretli = str(uyelik.kullanici_id) in secilen
                katilim = mevcut_katilimlar.get(uyelik.kullanici_id)

                # Takım yalnızca sahaya çıkanlara verilir; oynamayanın
                # takımı temizlenir ki eski atama ortalıkta kalmasın.
                takim = ""
                if isaretli:
                    secim = (request.POST.get(f"takim_{uyelik.kullanici_id}") or "").strip()
                    if secim in gecerli_takimlar:
                        takim = secim

                if isaretli:
                    # İşaretlemek "bu oyuncu oynuyor" demek: hem kadro kararı
                    # hem yoklama yanıtı "Geliyorum" oluyor.
                    #
                    # Yanıtı da yazmak şart, çünkü maç sayfasındaki katılım
                    # listesi ve sayaçlar (Mac.sayim) yalnızca `yanit` alanına
                    # bakıyor. Bir ara yalnızca `katildi` güncelleniyordu:
                    # yönetici oyuncuyu kadroya alıyor ama katılım listesinde
                    # hiçbir şey değişmiyordu, çünkü oyuncunun eski yanıtı
                    # olduğu gibi duruyordu.
                    if katilim:
                        katilim.katildi = True
                        katilim.takim = takim
                        katilim.yanit = Katilim.Yanit.GELIYORUM
                        katilim.save(
                            update_fields=["katildi", "takim", "yanit", "guncellenme"]
                        )
                    else:
                        Katilim.objects.create(
                            mac=mac,
                            kullanici=uyelik.kullanici,
                            katildi=True,
                            takim=takim,
                            yanit=Katilim.Yanit.GELIYORUM,
                        )
                    continue

                # --- İşaretsiz -----------------------------------------
                #
                # Burada oyuncuyu "gelmiyor" diye işaretlemek YOK. Eskiden
                # kadro her kaydedildiğinde işaretsiz herkese katildi=False
                # ve yanıt yoksa "Yokum" yazılıyordu; yani yönetici ilk
                # taslağı kaydettiği anda yoklamaya hiç cevap vermemiş
                # herkes "gelmiyorum" demiş sayılıyordu ve sonradan
                # işaretlendiklerinde bile yanıtları "Yokum" kalıyordu.
                #
                # Artık:
                #   kaydı olmayan       dokunulmuyor (yanıt vermemiş demek)
                #   "Geliyorum" diyen   katildi=False, yani yönetici kararı
                #                       yanıtın önüne geçiyor; kutunun
                #                       işaretini kaldırmak böyle çalışıyor
                #   diğerleri           katildi=None, karar yok, yanıt geçerli
                #
                # Yanıt alanına hiç dokunulmuyor: o oyuncunun kendi beyanı.
                if not katilim:
                    continue

                yeni_katildi = (
                    False if katilim.yanit == Katilim.Yanit.GELIYORUM else None
                )
                if katilim.katildi != yeni_katildi or katilim.takim != "":
                    katilim.katildi = yeni_katildi
                    katilim.takim = ""
                    katilim.save(update_fields=["katildi", "takim", "guncellenme"])

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

            # --- Forma golü ---------------------------------------------
            # Skor girilmemişse forma golü de anlamsız; birlikte temizleniyor.
            forma = (request.POST.get("forma_golu") or "").strip()
            mac.forma_golu = (
                forma if forma in gecerli_takimlar and mac.skor_girildi_mi else ""
            )

            mac.save(update_fields=["skor_a", "skor_b", "forma_golu", "guncellenme"])

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

    # Maç oynanmadan da açılabiliyor: yönetici kadroyu önceden kurup
    # dizilimi planlayabilsin, oyuncular da nerede oynayacaklarını görebilsin.
    # Puan rozetleri ve maçın adamı yalnızca veri oluştuğunda görünür.
    adam_idleri = {a["kullanici"].pk for a in macin_adami(mac)}
    takimlar = dizilim_verisi(mac, adam_idleri)

    # Puanları görebilmek için maçta oynayan herkesi puanlamış olmak
    # gerekiyor (süre dolduysa ya da yöneticiyse serbest).
    durum = puan_gorunurlugu(mac, request.user)
    if not durum.gorebilir:
        takimlar = puanlari_gizle(takimlar)

    return render(
        request,
        "matches/dizilim.html",
        {
            "mac": mac,
            "grup": mac.grup,
            "takimlar": takimlar,
            "yonetici_mi": mac.grup.yonetici_mi(request.user),
            "duzenlenebilir": False,
            "durum": durum,
        },
    )


@login_required
def dizilim_gorseli(request, mac_id: int):
    """
    Dizilimin paylaşılabilir PNG hâli.

    `?yon=yatay` (varsayılan) ya da `?yon=dikey`. Dikey, telefon hikâyesi
    ölçüsünde (1080x1920) ve eksenleri değişmiş olarak çiziliyor.

    Tema, kişinin sitede kullandığı temadan geliyor: koyu temada gezinen
    biri koyu zeminli bir görsel indiriyor. Ekranda koyu tema kullanırken
    açık zeminli bir görsel inince, indirilen şey bakılan şeye benzemiyordu.
    `?tema=acik|koyu` ile açıkça da istenebilir.

    Puan görünürlüğü sayfayla aynı kurala tabi: puanlamasını tamamlamamış
    kişinin görselinde de puan, ortalama ve maçın adamı çıkmıyor.
    """
    from apps.core.context_processors import GECERLI_TEMALAR, TEMA_COOKIE

    from .gorsel import YONLER, dizilim_gorseli as ciz, dosya_adi

    mac = _mac_getir(request, mac_id)

    yon = request.GET.get("yon", "yatay")
    if yon not in YONLER:
        yon = "yatay"

    tema = request.GET.get("tema") or request.COOKIES.get(TEMA_COOKIE, "acik")
    if tema not in GECERLI_TEMALAR:
        tema = "acik"

    adam_idleri = {a["kullanici"].pk for a in macin_adami(mac)}
    takimlar = dizilim_verisi(mac, adam_idleri)
    if not puan_gorunurlugu(mac, request.user).gorebilir:
        takimlar = puanlari_gizle(takimlar)

    icerik = ciz(mac, takimlar, yon, tema)

    yanit = HttpResponse(icerik, content_type="image/png")
    yanit["Content-Disposition"] = f'attachment; filename="{dosya_adi(mac, yon)}"'
    # Puan durumu kişiden kişiye değiştiği için paylaşımlı önbellek olmaz.
    yanit["Cache-Control"] = "private, max-age=0, no-store"
    return yanit


@login_required
def dizilim_duzenle(request, mac_id: int):
    """
    Dizilim düzenleyici: oyuncular sahada sürüklenerek yerleştirilir.

    Konumlar sahanın yüzdesi olarak geliyor (0-100). Piksel gelseydi farklı
    ekran genişliklerinde dizilim bozulurdu.
    """
    mac = _mac_getir(request, mac_id, yonetici_sart=True)

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
                # Oyuncu kendi takımının yarısının dışına çıkamaz. Tarayıcı
                # tarafında da engelleniyor ama sunucuda tekrar kırpıyoruz:
                # istemciden gelen hiçbir değere güvenilmez.
                katilim.poz_x = x_kirp(int(float(ham_x)), katilim.takim)
                katilim.poz_y = max(0, min(100, int(float(ham_y))))
            except (TypeError, ValueError):
                continue

            katilim.gol = _sayi(request.POST.get(f"gol_{kullanici_id}"), 0, 30)
            katilim.asist = _sayi(request.POST.get(f"asist_{kullanici_id}"), 0, 30)
            katilim.sari_kart = _sayi(request.POST.get(f"sari_{kullanici_id}"), 0, 2)
            katilim.kirmizi_kart = request.POST.get(f"kirmizi_{kullanici_id}") == "1"
            guncellenecek.append(katilim)

        hata = _istatistik_tutarli_mi(mac, guncellenecek)
        if hata:
            messages.error(request, hata)
            return redirect("matches:dizilim_duzenle", mac_id=mac.pk)

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
            # Düzenleme yalnızca yöneticide; yöneticiler puan kısıtından muaf.
            "durum": puan_gorunurlugu(mac, request.user),
        },
    )


def _sayi(ham, en_az: int, en_cok: int) -> int:
    """Formdan gelen sayıyı güvenli aralığa kırpar."""
    try:
        return max(en_az, min(en_cok, int(ham)))
    except (TypeError, ValueError):
        return en_az


def _istatistik_tutarli_mi(mac: Mac, katilimlar: list) -> str:
    """
    Girilen gol ve asistlerin skorla tutarlılığını denetler.

    Bir takımın oyuncularının attığı gollerin toplamı, o takımın skorunu
    aşamaz; asist için de aynısı geçerli (her golün en fazla bir asisti
    olabilir). Aksi hâlde "3-1 biten maçta 5 gol atmış" gibi kayıtlar
    oluşuyor ve istatistik sayfası saçmalıyor.

    Forma golü olan takımda sınır bir fazla: o gol gerçekten atıldı, sadece
    skor tabelasına yazılmadı. Golü atan oyuncu kendi istatistiğinde
    hakkını alıyor.

    Skor girilmemişse denetlenecek bir üst sınır yok; boş dizge döner.
    Hata varsa kullanıcıya gösterilecek mesajı döner.
    """
    if not mac.skor_girildi_mi:
        return ""

    skorlar = {Mac.Takim.A: mac.skor_a, Mac.Takim.B: mac.skor_b}

    for takim, skor in skorlar.items():
        takimdakiler = [k for k in katilimlar if k.takim == takim]
        if not takimdakiler:
            continue

        sinir = skor + (1 if mac.forma_golu == takim else 0)
        forma_notu = " (forma golü dâhil)" if sinir > skor else ""

        gol = sum(k.gol for k in takimdakiler)
        asist = sum(k.asist for k in takimdakiler)
        ad = dict(Mac.Takim.choices)[takim]

        if gol > sinir:
            return (
                f"{ad} için girilen gol toplamı ({gol}) en fazla "
                f"{sinir} olabilir{forma_notu}. Skoru düzelt ya da golleri azalt."
            )
        if asist > sinir:
            return (
                f"{ad} için girilen asist toplamı ({asist}) en fazla "
                f"{sinir} olabilir{forma_notu}. Her golün en fazla bir asisti olabilir."
            )
    return ""


# ---------------------------------------------------------------------------
# Çevrimdışı için sıradaki maç
# ---------------------------------------------------------------------------
@login_required
@require_GET
def sonraki_mac_ozeti(request):
    """
    Cihazda saklanmak üzere SIRADAKİ maçın özeti.

    Sahanın önünde, telefonunda çekmezken insanın istediği tek şey bu:
    saat kaçta, hangi sahada, kim geliyor, kim hangi takımda.

    NE DÖNÜYOR, NE DÖNMÜYOR — bu ayrım bilinçli. Servis çalışanının
    tasarım kuralı "kullanıcıya ait hiçbir şey cihazda kalmaz" idi, çünkü
    telefon elden ele geziyor. O kuralı toptan kaldırmak yerine daraltıyoruz:

      döner    : tarih, saat, saha, süre, kadro adları, takım dağılımı
      dönmez   : puanlar, maçın adamı, sohbet, fotoğraflar, geçmiş maçlar,
                 grup listesi, başka hiçbir maç

    Yani cihazda kalan en kötü şey "perşembe 21:00'de şu sahada şu on kişi
    oynuyor" oluyor. Puan ve sohbet asla diske inmiyor.

    Kaydetme VARSAYILAN OLARAK KAPALI; kullanıcı panelden açıyor
    (bkz. static/js/cevrimdisi.js). Kapalıyken bu uca hiç istek gitmiyor.
    """
    from apps.groups.models import Uyelik

    grup_idleri = Uyelik.objects.filter(
        kullanici=request.user, durum=Uyelik.Durum.ONAYLI
    ).values_list("grup_id", flat=True)

    mac = (
        Mac.objects.filter(
            grup_id__in=grup_idleri, iptal=False, baslangic__gte=timezone.now()
        )
        .select_related("grup")
        .order_by("baslangic")
        .first()
    )
    if mac is None:
        return JsonResponse({"tamam": True, "mac": None})

    yerel = timezone.localtime(mac.baslangic)
    takimlar = []
    if mac.takimlar_kurulmus_mu:
        for kod, ad in Mac.Takim.choices:
            takimlar.append(
                {
                    "ad": ad,
                    "oyuncular": [
                        k.kullanici.gorunen_ad for k in mac.takim_katilimlari(kod)
                    ],
                }
            )

    # Takım kurulmamışsa "geliyorum" diyenler; saha önünde asıl merak edilen bu.
    gelenler = [
        k.kullanici.gorunen_ad
        for k in mac.oynayan_katilimlar()
    ]

    return JsonResponse(
        {
            "tamam": True,
            "mac": {
                "grup": mac.grup.ad,
                "baslangic": mac.baslangic.isoformat(),
                "gun": f"{yerel:%d.%m.%Y}",
                "saat": f"{yerel:%H:%M}",
                "konum": mac.konum,
                "sure_dakika": mac.sure_dakika,
                "gelenler": sorted(gelenler, key=str.lower),
                "takimlar": takimlar,
                "adres": reverse("matches:detay", kwargs={"mac_id": mac.pk}),
            },
            # İstemci bunu gösteriyor: "23.08 14:10 itibarıyla".
            "guncellendi": timezone.now().isoformat(),
        }
    )
