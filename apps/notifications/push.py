"""
Web Push gönderimi.

Uygulamanın bildirimleri eksiksizdi ama çekmeliydi: kişi maçın saatinin
değiştiğini ancak uygulamayı bir dahaki açışında öğreniyordu. Burası o
bildirimleri telefona itiyor.

İÇERİK KURALI — bu dosyadaki en önemli şey
------------------------------------------
Sohbet uçtan uca şifreli. Sunucu mesaj metnini OKUYAMIYOR, dolayısıyla
bildirime de koyamıyor. Sohbet bildirimi yalnızca "yeni mesaj var" diyor;
metin, uygulama açılıp mesajı tarayıcıda çözünce görünüyor.

Maç, yoklama, iptal ve puanlama bildirimleri metin taşıyabiliyor, çünkü o
metni zaten sunucunun kendisi yazıyor (bkz. apps/notifications/models.py).

VAPID anahtarları
-----------------
.env içindeki VAPID_ACIK_ANAHTAR / VAPID_OZEL_ANAHTAR'dan geliyor. İkisi de
boşsa gönderim sessizce atlanıyor: uygulama bildirimsiz çalışmaya devam
ediyor, hata vermiyor. Anahtar üretmek için:

    python manage.py vapid_anahtari
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

guvenlik_log = logging.getLogger("halisaha.guvenlik")
log = logging.getLogger(__name__)

# Bu türlerin metni sunucudan geliyor, taşınabilir.
METIN_TASIYABILEN = {
    "yeni_mac",
    "mac_guncellendi",
    "mac_iptal",
    "yoklama_acildi",
    "puanlama_acildi",
    "katilma_istegi",
    "katilma_onaylandi",
    "katilma_reddedildi",
    "yonetici_yapildi",
    "gruptan_cikarildi",
    "macin_adami",
    "supheli_oylama",
    "puanlarin_silindi",
    "icerik_bildirildi",
}


def push_acik_mi() -> bool:
    """Anahtarlar tanımlı mı? Değilse gönderim yapılmıyor."""
    return bool(
        getattr(settings, "VAPID_ACIK_ANAHTAR", "")
        and getattr(settings, "VAPID_OZEL_ANAHTAR", "")
    )


def _yuk(bildirim) -> str:
    """
    Cihaza gidecek JSON.

    Sohbet bildirimi metin taşımıyor; sunucu şifreli mesajı okuyamadığı için
    zaten koyamaz. Diğerlerinde başlık ve mesaj sunucunun kendi yazdığı metin.
    """
    metin = bildirim.mesaj if bildirim.tur in METIN_TASIYABILEN else ""
    return json.dumps(
        {
            "baslik": bildirim.baslik,
            "mesaj": metin,
            "adres": bildirim.guvenli_url or "/panel/",
            "tur": bildirim.tur,
            # Aynı türden art arda gelen bildirimler üst üste yığılmasın.
            "etiket": f"{bildirim.tur}:{bildirim.alici_id}",
        },
        separators=(",", ":"),
    )


def bildirimi_it(bildirim) -> int:
    """
    Tek bir bildirimi, alıcının bütün cihazlarına gönderir.

    Başarıyla gönderilen cihaz sayısını döner. Gönderim başarısız olursa
    bildirim yine de uygulama içinde duruyor: push bir kolaylık, tek kanal
    değil. Bu yüzden hiçbir hata yukarı fırlatılmıyor — bildirim yazmak
    push yüzünden başarısız olmamalı.
    """
    if not push_acik_mi():
        return 0

    from .models import PushAbonelik

    abonelikler = list(PushAbonelik.objects.filter(kullanici_id=bildirim.alici_id))
    if not abonelikler:
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # pragma: no cover - paket kurulu değilse
        log.warning("pywebpush kurulu değil; push gönderilmiyor.")
        return 0

    from django.utils import timezone

    yuk = _yuk(bildirim)
    gonderilen = []
    olenler = []

    for abone in abonelikler:
        try:
            webpush(
                subscription_info={
                    "endpoint": abone.endpoint,
                    "keys": {"p256dh": abone.p256dh, "auth": abone.auth},
                },
                data=yuk,
                vapid_private_key=settings.VAPID_OZEL_ANAHTAR,
                vapid_claims={"sub": f"mailto:{settings.CONTACT_EMAIL}"},
                timeout=10,
            )
            gonderilen.append(abone.pk)
        except WebPushException as hata:
            kod = getattr(getattr(hata, "response", None), "status_code", None)
            # 404/410: abonelik ölmüş (uygulama silinmiş, izin geri alınmış).
            # Bunları tutmanın anlamı yok, her seferinde tekrar denenirdi.
            if kod in (404, 410):
                olenler.append(abone.pk)
            else:
                log.warning("Push gönderilemedi (abone=%s, kod=%s)", abone.pk, kod)
        except Exception:  # pragma: no cover - ağ/kütüphane hatası
            log.exception("Push gönderiminde beklenmeyen hata (abone=%s)", abone.pk)

    if olenler:
        PushAbonelik.objects.filter(pk__in=olenler).delete()
    if gonderilen:
        PushAbonelik.objects.filter(pk__in=gonderilen).update(
            son_kullanim=timezone.now()
        )
    return len(gonderilen)


def bildirimleri_it(bildirimler) -> int:
    """Birden çok bildirimi iter. Toplam gönderilen cihaz sayısını döner."""
    return sum(bildirimi_it(b) for b in bildirimler)
