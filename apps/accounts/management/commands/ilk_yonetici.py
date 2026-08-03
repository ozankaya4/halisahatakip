"""
Nihai yöneticiyi (ultimate admin) .env dosyasındaki değerlerden oluşturur.

Parola kaynak kodda tutulmaz; yalnızca ortam değişkeninden okunur:

    SUPERADMIN_EMAIL=...
    SUPERADMIN_PASSWORD=...
    SUPERADMIN_NAME=...

Kullanım:
    .venv\\Scripts\\python.exe manage.py ilk_yonetici

Komut çalıştıktan sonra parolayı .env dosyasından silmeniz önerilir.
"""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "SUPERADMIN_* ortam değişkenlerinden nihai yöneticiyi oluşturur/günceller."

    def add_arguments(self, parser):
        parser.add_argument(
            "--parola-guncelle",
            action="store_true",
            help="Kullanıcı zaten varsa parolasını da .env değeriyle günceller.",
        )

    @transaction.atomic
    def handle(self, *args, **secenekler):
        User = get_user_model()

        eposta = (os.environ.get("SUPERADMIN_EMAIL") or "").strip().lower()
        parola = os.environ.get("SUPERADMIN_PASSWORD") or ""
        ad = (os.environ.get("SUPERADMIN_NAME") or "").strip()

        if not eposta or not parola:
            raise CommandError(
                "SUPERADMIN_EMAIL ve SUPERADMIN_PASSWORD tanımlı değil.\n"
                ".env dosyanıza ekleyip komutu tekrar çalıştırın."
            )

        try:
            validate_password(parola)
        except ValidationError as hata:
            raise CommandError(
                "Parola güvenlik kurallarını karşılamıyor:\n  - "
                + "\n  - ".join(hata.messages)
            )

        kullanici = User.objects.filter(email=eposta).first()
        yeni_mi = kullanici is None

        if yeni_mi:
            kullanici = User.objects.create_superuser(
                email=eposta, password=parola, ad_soyad=ad or ""
            )
            self.stdout.write(self.style.SUCCESS(f"Nihai yönetici oluşturuldu: {eposta}"))
        else:
            kullanici.is_staff = True
            kullanici.is_superuser = True
            kullanici.is_active = True
            if ad:
                kullanici.ad_soyad = ad
            if secenekler["parola_guncelle"]:
                kullanici.set_password(parola)
                self.stdout.write(self.style.WARNING("Parola güncellendi."))
            kullanici.save()
            self.stdout.write(
                self.style.SUCCESS(f"Mevcut hesap nihai yönetici yapıldı: {eposta}")
            )

        # allauth e-posta doğrulaması zorunlu olduğu için adresi doğrulanmış
        # olarak işaretliyoruz; aksi hâlde yönetici giriş yapamaz.
        try:
            from allauth.account.models import EmailAddress

            EmailAddress.objects.update_or_create(
                user=kullanici,
                email=eposta,
                defaults={"verified": True, "primary": True},
            )
        except Exception as hata:  # pragma: no cover
            self.stdout.write(
                self.style.WARNING(f"E-posta doğrulama kaydı yazılamadı: {hata}")
            )

        self.stdout.write(
            "\nParolayı .env dosyasından silmeyi unutmayın. "
            "Giriş: /hesap/login/  ·  Yönetim: /yonetim/"
        )
