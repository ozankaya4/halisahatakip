"""
Halısaha Takip — Django ayarları.

Ortama özel her değer .env dosyasından okunur. Kaynak kodda hiçbir sır tutulmaz.
Yerelde SQLite ile çalışır; DATABASE_URL verildiğinde PostgreSQL'e geçer.
"""

from pathlib import Path

import environ
from csp.constants import NONE, SELF

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["127.0.0.1", "localhost"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    DATABASE_URL=(str, f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
    SECURE_SSL_REDIRECT=(bool, False),
    BEHIND_PROXY=(bool, False),
    USE_X_ACCEL_REDIRECT=(bool, False),
    EMAIL_BACKEND=(str, "django.core.mail.backends.console.EmailBackend"),
    EMAIL_HOST=(str, ""),
    EMAIL_PORT=(int, 587),
    EMAIL_HOST_USER=(str, ""),
    EMAIL_HOST_PASSWORD=(str, ""),
    EMAIL_USE_TLS=(bool, True),
    DEFAULT_FROM_EMAIL=(str, "Halısaha Takip <noreply@localhost>"),
    GOOGLE_CLIENT_ID=(str, ""),
    GOOGLE_CLIENT_SECRET=(str, ""),
    PUBLIC_PROFILES=(bool, False),
)

environ.Env.read_env(BASE_DIR / ".env")

# --------------------------------------------------------------------------
# Temel
# --------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Profil sayfaları giriş yapmamış ziyaretçilere de açık olsun mu?
# Varsayılan: hayır (yalnızca giriş yapmış kullanıcılar görebilir).
PUBLIC_PROFILES = env("PUBLIC_PROFILES")

# Uygulama bir ters vekil sunucunun (nginx) arkasında mı çalışıyor?
# Modül düzeyinde tanımlı olması şart: yalnızca burada env() ile okunup
# atılırsa, uygulama kodu (örn. accounts/adapters.py içindeki
# get_client_ip) vekil arkasında olup olmadığını öğrenemez.
BEHIND_PROXY = env("BEHIND_PROXY")

# Google girişi yalnızca kimlik bilgileri girildiğinde etkinleşir. Aksi hâlde
# giriş sayfasında tıklandığında hata veren ölü bir düğme görünürdü.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
GOOGLE_AKTIF = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Üçüncü taraf
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    *(["allauth.socialaccount.providers.google"] if GOOGLE_AKTIF else []),
    "axes",
    # Proje uygulamaları
    "apps.core",
    "apps.accounts",
    "apps.groups",
    "apps.notifications",
    "apps.matches",
    "apps.ratings",
    "apps.chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise yalnızca üretimde: geliştirmede statik dosyaları Django'nun
    # kendi runserver'ı sunuyor, aksi hâlde her istekte STATIC_ROOT uyarısı çıkar.
    *([] if DEBUG else ["whitenoise.middleware.WhiteNoiseMiddleware"]),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    # axes en sonda olmalı ki kimlik doğrulama sonrası devreye girsin
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "halisaha.urls"
WSGI_APPLICATION = "halisaha.wsgi.application"
ASGI_APPLICATION = "halisaha.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.notifications.context_processors.unread_notifications",
                "apps.core.context_processors.site_chrome",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Veritabanı
# --------------------------------------------------------------------------
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
if DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
    DATABASES["default"]["CONN_MAX_AGE"] = 60
    DATABASES["default"].setdefault("OPTIONS", {})["sslmode"] = env(
        "DB_SSLMODE", default="prefer"
    )

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Kimlik doğrulama
# --------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    # axes en başta olmalı ki kilitli hesaplar erken reddedilsin
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Argon2 en başta: Django'nun varsayılan PBKDF2'sinden belirgin şekilde güçlü.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "core:home"

# --- allauth ---------------------------------------------------------------
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
# Kullanıcı modelimizde username alanı yok; allauth'a bunu açıkça söylüyoruz.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_EMAIL_VERIFICATION = "mandatory" if not DEBUG else "optional"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PRESERVE_USERNAME_CASING = False
ACCOUNT_SESSION_REMEMBER = None
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False
ACCOUNT_LOGOUT_ON_GET = False  # GET ile çıkış CSRF'e açıktır
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Halısaha Takip] "
ACCOUNT_ADAPTER = "apps.accounts.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "apps.accounts.adapters.SocialAccountAdapter"
ACCOUNT_SIGNUP_FORM_CLASS = "apps.accounts.forms.KayitFormu"
ACCOUNT_RATE_LIMITS = {
    "login_failed": "5/5m/ip",
    "signup": "10/h/ip",
    "reset_password": "5/h/ip",
    "confirm_email": "3/10m/key",
}

SOCIALACCOUNT_ONLY = False
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"  # Google e-postayı zaten doğruluyor
SOCIALACCOUNT_EMAIL_AUTHENTICATION = False
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_STORE_TOKENS = False  # ihtiyacımız yok; saklamamak daha güvenli
SOCIALACCOUNT_PROVIDERS = (
    {
        "google": {
            "APP": {
                "client_id": GOOGLE_CLIENT_ID,
                "secret": GOOGLE_CLIENT_SECRET,
                "key": "",
            },
            "SCOPE": ["profile", "email"],
            "AUTH_PARAMS": {"access_type": "online"},
            "OAUTH_PKCE_ENABLED": True,
            "VERIFIED_EMAIL": True,
        }
    }
    if GOOGLE_AKTIF
    else {}
)

# --- django-axes (kaba kuvvet koruması) ------------------------------------
AXES_FAILURE_LIMIT = 6
AXES_COOLOFF_TIME = 1  # saat
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ADMIN = True
AXES_LOCKOUT_TEMPLATE = "accounts/kilitlendi.html"
AXES_VERBOSE = True
# Ters vekil sunucunun arkasındayken bile 0 (None) olmalı.
#
# nginx yapılandırmamız X-Forwarded-For başlığını EKLEMİYOR, ÜZERİNE YAZIYOR
# (proxy_set_header X-Forwarded-For $remote_addr). Böylece başlıkta her zaman
# tek bir değer var: gerçek istemcinin adresi.
#
# Burada 1 yazsaydık ipware soldan ikinci değeri okurdu. nginx eklemeli
# ($proxy_add_x_forwarded_for) çalışsaydı, saldırgan kendi isteğine
# "X-Forwarded-For: 1.2.3.4" koyup kilitlemenin hangi IP'ye yazılacağını
# kendisi seçebilirdi: kendi kilidini atlatabilir ya da başkasını
# kilitleyebilirdi. İki ayarı birlikte değiştirmek gerekir.
AXES_IPWARE_PROXY_COUNT = None
AXES_IPWARE_META_PRECEDENCE_ORDER = (
    ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")
    if BEHIND_PROXY
    else ("REMOTE_ADDR",)
)

# --------------------------------------------------------------------------
# Uluslararasılaştırma — uygulama tamamen Türkçe
# --------------------------------------------------------------------------
LANGUAGE_CODE = "tr"
LANGUAGES = [("tr", "Türkçe")]
TIME_ZONE = "Europe/Istanbul"
USE_I18N = True
USE_TZ = True
FIRST_DAY_OF_WEEK = 1  # Pazartesi

# --------------------------------------------------------------------------
# Statik dosyalar ve medya
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Yüklenen dosyalar web kökünün dışında tutulur ve yalnızca yetki kontrolünden
# geçen bir görünüm üzerinden sunulur (bkz. apps/core/views.py: korumali_medya).
MEDIA_ROOT = BASE_DIR / "media"
# Bu yol hiçbir zaman bir URL kalıbına bağlanmaz; doğrudan sunum bilinçli olarak
# kapalıdır. Dosyalar /dosya/<tur>/<uuid>/ üzerinden yetki kontrolüyle sunulur.
MEDIA_URL = "/dogrudan-erisim-kapali/"

# Manifest tabanlı depolama "collectstatic" çalıştırılmasını gerektirir; bu
# yüzden yalnızca üretimde devreye giriyor. Geliştirmede ve testlerde düz
# depolama kullanılır.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# nginx arkasındayken dosyayı Django yerine nginx göndersin (hızlı + güvenli)
USE_X_ACCEL_REDIRECT = env("USE_X_ACCEL_REDIRECT")

# --- Yükleme sınırları -----------------------------------------------------
MAX_UPLOAD_SIZE = 8 * 1024 * 1024  # 8 MB, tek dosya
MAX_IMAGE_DIMENSION = 6000  # px, kenar başına — dekompresyon bombası koruması
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 500
DATA_UPLOAD_MAX_NUMBER_FILES = 20
FILE_UPLOAD_PERMISSIONS = 0o644

# --------------------------------------------------------------------------
# Güvenlik
# --------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "hst_sessionid"
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 14 gün

CSRF_COOKIE_HTTPONLY = False  # fetch çağrıları için JS'in okuması gerekiyor
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "hst_csrftoken"
CSRF_USE_SESSIONS = False

# HTTPS'e özel ayarlar yalnızca üretimde açılır
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
if SECURE_SSL_REDIRECT:
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# --- İçerik Güvenlik Politikası --------------------------------------------
# Satır içi script yok; her şey kendi kaynağımızdan yüklenir. Uçtan uca
# şifrelemenin XSS'e karşı anlamlı olması için bu politikanın sıkı kalması şart.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [NONE],
        "script-src": [SELF],
        "style-src": [SELF],
        "img-src": [SELF, "data:", "blob:"],
        "font-src": [SELF],
        "connect-src": [SELF],
        "form-action": [SELF, "https://accounts.google.com"],
        "frame-ancestors": [NONE],
        "base-uri": [SELF],
        "object-src": [NONE],
        "manifest-src": [SELF],
        "worker-src": [SELF],
        "upgrade-insecure-requests": True if SECURE_SSL_REDIRECT else False,
    }
}

# --------------------------------------------------------------------------
# E-posta
# --------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND")
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_PORT = env("EMAIL_PORT")
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env("EMAIL_USE_TLS")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")

# --------------------------------------------------------------------------
# Uygulama kuralları (soruların yanıtlarına göre)
# --------------------------------------------------------------------------
# Maç sonrası puanlama penceresi: maç saatinden itibaren 1 hafta
RATING_WINDOW_DAYS = 7
# Yalnızca maça katılanlar puan verebilir
RATING_REQUIRES_ATTENDANCE = True
# Kimse kendine puan veremez
RATING_ALLOW_SELF = False
# Tek tek puanlar gizli; yalnızca ortalama gösterilir
RATING_ANONYMOUS = True
# Ortalamanın profilde görünmesi için gereken en az puan sayısı
RATING_MIN_VOTES_TO_DISPLAY = 3

# Davet bağlantısı varsayılanları
INVITE_DEFAULT_TTL_DAYS = 7
INVITE_MAX_USES_DEFAULT = 25

MESSAGES_PAGE_SIZE = 50

# --------------------------------------------------------------------------
# Günlükleme
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.security": {"handlers": ["console"], "level": "INFO"},
        "halisaha.guvenlik": {"handlers": ["console"], "level": "INFO"},
        "axes": {"handlers": ["console"], "level": "WARNING"},
    },
}
