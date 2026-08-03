"""
Basit hız sınırlama.

Django önbelleğini kullanır. Varsayılan yerel bellek (locmem) önbelleğinde
sayaç süreç başınadır; birden çok worker ile çalıştırırken CACHES ayarını
Redis/Memcached'e almanız gerekir (bkz. README, "Üretim" bölümü).

Kimlik doğrulama denemeleri bu mekanizmaya bırakılmaz; onlar için
django-axes ve allauth'un kendi sınırları devrededir.
"""

from __future__ import annotations

from django.core.cache import cache


def istemci_ip(request) -> str:
    """
    İstemci IP'si.

    X-Forwarded-For yalnızca BEHIND_PROXY açıkken ve en sağdaki güvenilen
    vekilden bir önceki değer olarak dikkate alınır; aksi hâlde istemci
    başlığı uydurup sınırı atlayabilirdi.
    """
    from django.conf import settings

    if getattr(settings, "BEHIND_PROXY", False) or settings.SECURE_PROXY_SSL_HEADER:
        iletilen = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if iletilen:
            parcalar = [p.strip() for p in iletilen.split(",") if p.strip()]
            if parcalar:
                return parcalar[-1]
    return request.META.get("REMOTE_ADDR", "bilinmiyor")


def sinir_asildi(anahtar: str, limit: int, saniye: int) -> bool:
    """
    Sayaç artırır; sınır aşıldıysa True döner.

    `anahtar` çağıran tarafından anlamlı biçimde oluşturulmalıdır, örn.
    f"katil:{kullanici.pk}".
    """
    onbellek_anahtari = f"hs:{anahtar}"
    mevcut = cache.get(onbellek_anahtari)
    if mevcut is None:
        cache.set(onbellek_anahtari, 1, timeout=saniye)
        return False
    try:
        yeni = cache.incr(onbellek_anahtari)
    except ValueError:
        # Anahtar iki okuma arasında düştü.
        cache.set(onbellek_anahtari, 1, timeout=saniye)
        return False
    return yeni > limit
