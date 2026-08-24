"""
Üretim ayarı denetimleri.

`python manage.py check --deploy` bunları çalıştırıyor. README dağıtım
adımlarında bu komutun **sıfır uyarı** vermesini şart koşuyor; buraya
eklenen her kontrol o kapıya takılıyor.

Django'nun kendi --deploy kontrolleri yalnızca çerçevenin ayarlarına bakıyor
(HSTS, çerezler, DEBUG…). Uygulamanın kendi güvenlik varsayımları — kimin
kayıt olabildiği, hız sınırlarının gerçekten sayıp saymadığı — Django'nun
göremeyeceği yerlerde duruyor ve tam da bu yüzden sessizce yanlış
yapılandırılabiliyor.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Warning as CheckWarning
from django.core.checks import register

# Süreç başına sayan önbellek arka uçları. Birden çok gunicorn işçisiyle
# çalışırken her işçi kendi sayacını tutuyor.
SUREC_BASINA_ONBELLEKLER = (
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.dummy.DummyCache",
)


@register("security", deploy=True)
def eposta_dogrulamasi_acik_mi(app_configs, **kwargs):
    """
    Üretimde e-posta doğrulaması kapalıysa uyarır.

    ACCOUNT_EMAIL_VERIFICATION="none" iken herkes, sahibi olmadığı bir
    e-posta adresiyle kayıt olup anında giriş yapabiliyor. İki somut sonucu
    var:

      * Başkasının adresiyle hesap açılabiliyor; adresin gerçek sahibi
        haberdar bile olmuyor (doğrulama e-postası hiç gitmiyor).
      * Adres bir kez alındığında ACCOUNT_UNIQUE_EMAIL yüzünden gerçek
        sahibi aynı adresle ne kayıt olabiliyor ne de Google ile
        girebiliyor — kendi adresinden kilitlenmiş oluyor.

    Değer .env'deki EMAIL_VERIFICATION ile ayarlanıyor ve varsayılanı
    "none". DEBUG'a bağlı değil: README bir dönem "DEBUG=False olunca
    zorunlu hâle gelir" diyordu, kodda öyle bir bağ hiç olmadı. Bu kontrol
    o boşluğu kapatıyor.
    """
    if settings.DEBUG:
        return []
    if getattr(settings, "ACCOUNT_EMAIL_VERIFICATION", "none") != "none":
        return []
    return [
        CheckWarning(
            "E-posta doğrulaması kapalı: herkes sahibi olmadığı bir adresle "
            "kayıt olup anında giriş yapabilir.",
            hint=(
                ".env dosyasına EMAIL_VERIFICATION=mandatory yazın ve ÇALIŞAN "
                "bir SMTP yapılandırın (EMAIL_BACKEND=...smtp.EmailBackend). "
                "SMTP olmadan 'mandatory' seçilirse hiç kimse kayıt olamaz."
            ),
            id="halisaha.W001",
        )
    ]


@register("security", deploy=True)
def hiz_siniri_onbellegi_paylasimli_mi(app_configs, **kwargs):
    """
    Hız sınırlarının gerçekten saydığını doğrular.

    apps/core/ratelimit.py ve allauth'un ACCOUNT_RATE_LIMITS ayarı Django
    önbelleğini kullanıyor. Varsayılan LocMemCache süreç başına ayrı bir
    sözlük; deploy/gunicorn.conf.py ise 5 işçi başlatıyor. O hâlde
    "5/5m/ip" olarak yazılan giriş sınırı pratikte 25/5m/ip oluyor ve
    saldırgan işçiler arasında dolaştıkça sınır iyice gevşiyor.

    django-axes bundan etkilenmiyor (sayacı veritabanında), yani hesap
    kilidi çalışmaya devam ediyor. Etkilenen: allauth'un giriş/kayıt/parola
    sıfırlama sınırları ve uygulamanın kendi sınırları (davet, puanlama,
    mesaj, fotoğraf, şikâyet).

    README bunu "Üretim → Önbellek (önemli)" başlığında anlatıyor ama
    ayarın yapıldığını kimse denetlemiyordu.
    """
    if settings.DEBUG:
        return []
    arka_uc = settings.CACHES.get("default", {}).get("BACKEND", "")
    if arka_uc not in SUREC_BASINA_ONBELLEKLER:
        return []
    return [
        CheckWarning(
            f"Hız sınırlama önbelleği süreç başına tutuluyor ({arka_uc}). "
            "Birden çok gunicorn işçisiyle sınırlar işçi sayısı kadar gevşer.",
            hint=(
                "CACHES['default'] ayarını Redis ya da Memcached'e alın "
                "(bkz. README, 'Üretime alma → Önbellek'). Tek işçiyle "
                "çalışıyorsanız bu uyarıyı yok sayabilirsiniz."
            ),
            id="halisaha.W002",
        )
    ]
