"""
Web Push için VAPID anahtar çifti üretir.

    python manage.py vapid_anahtari

Çıktıdaki iki satırı .env dosyasına yapıştırın. Anahtarlar bir kez üretilir
ve DEĞİŞTİRİLMEZ: özel anahtarı değiştirmek, o ana kadarki bütün cihaz
aboneliklerini geçersiz kılar ve herkesin bildirim iznini yeniden vermesi
gerekir.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Web Push için VAPID anahtar çifti üretir."

    def handle(self, *args, **secenekler):
        # Windows konsolu varsayılan olarak cp1252; Türkçe harfler çıktıyı
        # UnicodeEncodeError ile patlatıyordu. Komutun tek işi iki satır
        # yazdırmak, o yüzden akışı burada UTF-8'e çeviriyoruz.
        import sys

        for akis in (sys.stdout, sys.stderr):
            try:
                akis.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):  # pragma: no cover
                pass

        try:
            from py_vapid import Vapid02
        except ImportError:
            raise SystemExit(
                "py_vapid kurulu değil. Önce: pip install -r requirements.txt"
            )

        import base64

        from cryptography.hazmat.primitives import serialization

        vapid = Vapid02()
        vapid.generate_keys()

        ozel = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        acik = vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )

        def b64(veri: bytes) -> str:
            return base64.urlsafe_b64encode(veri).decode("ascii").rstrip("=")

        self.stdout.write("")
        self.stdout.write(".env dosyasına ekleyin:")
        self.stdout.write("")
        self.stdout.write(f"VAPID_ACIK_ANAHTAR={b64(acik)}")
        self.stdout.write(f"VAPID_OZEL_ANAHTAR={b64(ozel)}")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "Özel anahtarı kimseyle paylaşmayın ve DEĞİŞTİRMEYİN: "
                "değiştirmek bütün cihaz aboneliklerini geçersiz kılar."
            )
        )
