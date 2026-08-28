"""Sohbet anahtarı yaşam döngüsü — sunucu tarafındaki (şifresiz) mantık."""

from __future__ import annotations

import hashlib
import logging

from django.db import transaction

from .models import AnahtarPaketi, GrupAnahtari

guvenlik_log = logging.getLogger("halisaha.guvenlik")


def parmak_izi_hesapla(acik_jwk: dict) -> str:
    """
    Açık anahtarın parmak izi: SHA-256'nın ilk 16 baytı, dörderli gruplar.

    static/js/e2ee.js içindeki parmakIziHesapla() ile BİREBİR aynı sonucu
    vermek ZORUNDA. İkisi ayrı düşerse kullanıcı ekranda gördüğü parmak izini
    karşı tarafınkiyle karşılaştıramaz ve doğrulama fikri çöker;
    apps/core/tests.py bunu sabit bir vektörle sınıyor.

    Girdi kasten `n` ve `e` ile sınırlı: JWK'nın tamamı üzerinden hesaplamak,
    alan sırası ya da fazladan bir alan değiştiğinde parmak izini de
    değiştirirdi. `n` ve `e` RSA açık anahtarının kendisi; anahtar aynıysa
    parmak izi de aynı kalıyor.
    """
    veri = f"{acik_jwk['n']}.{acik_jwk['e']}".encode("utf-8")
    onalti = hashlib.sha256(veri).hexdigest()[:32]  # ilk 16 bayt
    return " ".join(onalti[i : i + 4] for i in range(0, 32, 4)).upper()


def aktif_anahtar(grup) -> GrupAnahtari | None:
    return (
        GrupAnahtari.objects.filter(grup=grup, aktif=True)
        .order_by("-surum")
        .first()
    )


def sonraki_surum(grup) -> int:
    son = GrupAnahtari.objects.filter(grup=grup).order_by("-surum").first()
    return (son.surum + 1) if son else 1


@transaction.atomic
def anahtari_dondur(grup, ayrilan_kullanici=None) -> None:
    """
    Bir üye gruptan çıktığında sohbet anahtarını geçersiz kılar.

    Sunucu yeni anahtarı **üretemez** (anahtar materyali sunucuda yok). Bu
    yüzden yaptığımız iki şey var:

      1. Mevcut sürümü pasife çekip "döndürülmeli" olarak işaretlemek.
      2. Ayrılan kişinin tüm sarmalanmış paketlerini silmek — böylece bir daha
         hiçbir sürümün anahtarını sunucudan alamaz.

    Yeni sürümü, anahtarı zaten açmış olan ilk üye sohbeti açtığında tarayıcı
    üretip yükler. O ana kadar sohbete yeni mesaj yazılamaz.

    Not: ayrılan kişi eski anahtarı daha önce indirmişse tarayıcısında hâlâ
    duruyor olabilir; geçmiş mesajları okumasını teknik olarak engelleyemeyiz.
    Sağladığımız güvence ileri yönlüdür: bundan sonraki mesajları okuyamaz.
    """
    GrupAnahtari.objects.filter(grup=grup, aktif=True).update(
        aktif=False, dondurulmeli=True
    )

    if ayrilan_kullanici is not None:
        silinen, _ = AnahtarPaketi.objects.filter(
            grup_anahtari__grup=grup, uye=ayrilan_kullanici
        ).delete()
        guvenlik_log.info(
            "Sohbet anahtarı döndürüldü: grup=%s ayrılan=%s silinen_paket=%s",
            grup.pk,
            getattr(ayrilan_kullanici, "pk", None),
            silinen,
        )


def eksik_paket_uyeleri(grup, grup_anahtari: GrupAnahtari):
    """
    Aktif anahtarın kendileri için henüz sarmalanmadığı onaylı üyeler.

    Yeni onaylanan üyeler buraya düşer. Anahtarı açık olan herhangi bir üye
    sohbeti açtığında istemci bu kişiler için sarmalama yapıp yükler.
    """
    from apps.groups.models import Uyelik

    paketi_olanlar = set(
        AnahtarPaketi.objects.filter(grup_anahtari=grup_anahtari).values_list(
            "uye_id", flat=True
        )
    )
    return [
        u
        for u in Uyelik.objects.filter(
            grup=grup, durum=Uyelik.Durum.ONAYLI
        ).select_related("kullanici", "kullanici__anahtar_cifti")
        if u.kullanici_id not in paketi_olanlar
        and hasattr(u.kullanici, "anahtar_cifti")
    ]
