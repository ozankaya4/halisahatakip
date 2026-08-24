"""
allauth uyarlayıcıları.

Buradaki asıl güvenlik kararı `pre_social_login` içinde: bir Google hesabını
mevcut bir yerel hesaba yalnızca **doğrulanmış** e-posta eşleşmesinde bağlıyoruz.
Sağlayıcı e-postayı doğrulamamışsa bağlama yapılmaz; aksi hâlde birinin
başkasının e-postasıyla sağlayıcıda hesap açıp o hesabı devralması mümkün olurdu.
"""

from __future__ import annotations

import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.core.exceptions import ValidationError

guvenlik_log = logging.getLogger("halisaha.guvenlik")


class AccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        return "/panel/"

    def get_client_ip(self, request):
        """
        İstemcinin IP adresi. allauth bunu hız sınırlaması için istiyor ve
        bulamazsa PermissionDenied fırlatıyor (giriş sayfası 403 veriyor).

        Üretimde gunicorn ile nginx arasında TCP değil **Unix soketi** var.
        Soketin karşı ucunda bir IP olmadığı için REMOTE_ADDR boş geliyor ve
        allauth'un varsayılan uygulaması çuvallıyor. Gerçek adres nginx'in
        koyduğu X-Forwarded-For başlığında.

        nginx yapılandırmamız bu başlığı EKLEMİYOR, ÜZERİNE YAZIYOR
        (proxy_set_header X-Forwarded-For $remote_addr), bu yüzden içinde tek
        ve gerçek adres bulunuyor; istemci kendi başlığını uydurup buraya
        istediğini yazdıramaz. Aynı sebeple settings.py'de
        AXES_IPWARE_PROXY_COUNT = None.

        Başlıkta birden çok değer varsa EN SAĞDAKİ alınır.

        Burada bir dönem en SOLDAKİ alınıyordu ve gerekçesi olarak "başlık
        bir gün eklemeli hâle gelirse gerçek istemci en solda olur" yazıyordu.
        Bu ters. nginx'in eklemeli biçimi ($proxy_add_x_forwarded_for)
        istemcinin gönderdiği değerin ARDINA kendi gördüğü adresi ekliyor:

            X-Forwarded-For: <istemcinin uydurduğu>, <nginx'in gördüğü>

        Yani eklemeli biçimde en soldaki değer saldırganın yazdığı şey, en
        sağdaki ise gerçek adres. Eski kod tam da korunmaya çalışılan durumda
        saldırganın seçtiği adresi kullanırdı: allauth'un giriş hız sınırını
        her istekte başka bir "IP" göstererek atlamak ya da başka birinin
        adresini kilitletmek mümkün olurdu.

        Üzerine yazan biçimde tek değer olduğu için sağdan okumak bugünkü
        davranışı değiştirmiyor; yalnızca yapılandırma değişirse güvenli
        tarafta kalıyoruz. apps/core/ratelimit.py de aynı kuralı uyguluyor,
        böylece iki hız sınırlama yolu aynı adresi görüyor.
        """
        if getattr(settings, "BEHIND_PROXY", False):
            iletilen = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
            if iletilen:
                parcalar = [p.strip() for p in iletilen.split(",") if p.strip()]
                if parcalar:
                    return parcalar[-1]
            gercek = (request.META.get("HTTP_X_REAL_IP") or "").strip()
            if gercek:
                return gercek
        return super().get_client_ip(request)

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        ad = (form.cleaned_data.get("ad_soyad") or "").strip()
        if ad:
            user.ad_soyad = ad[:80]
        if commit:
            user.save()
        return user

    def clean_email(self, email: str) -> str:
        return super().clean_email(email).lower().strip()


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        # Zaten bağlı bir sosyal hesap: yapacak bir şey yok.
        if sociallogin.is_existing:
            return

        eposta = (sociallogin.account.extra_data or {}).get("email")
        dogrulanmis = bool(
            (sociallogin.account.extra_data or {}).get("email_verified")
            or (sociallogin.account.extra_data or {}).get("verified_email")
        )
        if not eposta or not dogrulanmis:
            guvenlik_log.warning(
                "Doğrulanmamış sağlayıcı e-postası ile hesap bağlama reddedildi: %r",
                eposta,
            )
            return

        eposta = eposta.lower().strip()
        try:
            mevcut = EmailAddress.objects.get(email__iexact=eposta, verified=True)
        except EmailAddress.DoesNotExist:
            return
        except EmailAddress.MultipleObjectsReturned:
            guvenlik_log.error("Aynı e-posta birden fazla hesapta doğrulanmış: %s", eposta)
            return

        sociallogin.connect(request, mevcut.user)

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        ad = (data.get("name") or "").strip()
        if not ad:
            ad = " ".join(
                p for p in [data.get("first_name"), data.get("last_name")] if p
            ).strip()
        if ad:
            user.ad_soyad = ad[:80]
        if user.email:
            user.email = user.email.lower().strip()
        return user

    def is_auto_signup_allowed(self, request, sociallogin):
        # Google e-postayı doğruladığı için otomatik kayda izin veriyoruz.
        extra = sociallogin.account.extra_data or {}
        return bool(extra.get("email") and extra.get("email_verified"))
