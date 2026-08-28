"""
Uçtan uca duman testleri.

İki şeyi doğruluyoruz:
  1. Sayfalar gerçekten render oluyor (şablon hataları erken yakalansın).
  2. Yetki kuralları gerçekten uygulanıyor — özellikle "üye olmayan göremez",
     "kendine puan verilemez", "maçta oynamayan puanlayamaz".

Çalıştırmak için:
    .venv\\Scripts\\python.exe manage.py test
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.chat.models import AnahtarCifti
from apps.groups.models import DavetBagi, Grup, Uyelik, jeton_ozeti
from apps.matches.models import Katilim, Mac
from apps.ratings.models import Puan

User = get_user_model()


def kullanici(eposta: str, ad: str = "") -> "User":
    return User.objects.create_user(email=eposta, password="CokGuvenliParola123", ad_soyad=ad)


def gorsel_uret(boyut=(60, 40), bicim="JPEG") -> io.BytesIO:
    tampon = io.BytesIO()
    Image.new("RGB", boyut, (30, 90, 60)).save(tampon, format=bicim)
    tampon.seek(0)
    tampon.name = f"test.{bicim.lower()}"
    return tampon


class TemelSayfalarTesti(TestCase):
    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")

    def test_anasayfa_misafire_acilir(self):
        yanit = self.client.get(reverse("core:home"))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "Halısaha Defteri")

    def test_giris_sayfasi_render_oluyor(self):
        yanit = self.client.get(reverse("account_login"))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "Giriş yap")

    def test_kayit_sayfasi_render_oluyor(self):
        yanit = self.client.get(reverse("account_signup"))
        self.assertEqual(yanit.status_code, 200)

    def test_panel_giris_ister(self):
        yanit = self.client.get(reverse("core:dashboard"))
        self.assertEqual(yanit.status_code, 302)

    def test_panel_bos_durumu(self):
        self.client.force_login(self.ozan)
        yanit = self.client.get(reverse("core:dashboard"))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "Henüz bir grubun yok")

    def test_tema_cerezi_yazilir(self):
        yanit = self.client.post(
            reverse("core:tema_degistir"), {"tema": "koyu", "next": "/"}
        )
        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(yanit.cookies["hst_tema"].value, "koyu")

    def test_tema_acik_yonlendirmeyi_reddeder(self):
        """next parametresi dış siteye işaret ederse yok sayılmalı."""
        yanit = self.client.post(
            reverse("core:tema_degistir"),
            {"tema": "koyu", "next": "https://kotu-site.example/"},
        )
        self.assertEqual(yanit["Location"], "/")


class GrupAkisiTesti(TestCase):
    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.mert = kullanici("mert@example.com", "Mert Arslan")
        self.yabanci = kullanici("yabanci@example.com", "Yabancı Kişi")

        self.client.force_login(self.ozan)
        self.client.post(reverse("groups:olustur"), {"ad": "Perşembe Ekibi", "aciklama": ""})
        self.grup = Grup.objects.get(ad="Perşembe Ekibi")

    def test_kurucu_yonetici_olur(self):
        uyelik = self.grup.uyelik(self.ozan)
        self.assertEqual(uyelik.rol, Uyelik.Rol.YONETICI)
        self.assertEqual(uyelik.durum, Uyelik.Durum.ONAYLI)
        self.assertTrue(self.grup.yonetici_mi(self.ozan))

    def test_uye_olmayan_grubu_goremez(self):
        self.client.force_login(self.yabanci)
        yanit = self.client.get(reverse("groups:detay", args=[self.grup.genel_id]))
        self.assertEqual(yanit.status_code, 403)

    def test_davet_jetonu_veritabaninda_duz_tutulmaz(self):
        kayit, ham = DavetBagi.olustur(self.grup, self.ozan, gun=7, max_kullanim=5)
        self.assertNotEqual(kayit.jeton_ozet, ham)
        self.assertEqual(kayit.jeton_ozet, jeton_ozeti(ham))
        self.assertFalse(DavetBagi.objects.filter(jeton_ozet=ham).exists())

    def test_davetle_katilma_onay_bekler(self):
        _, ham = DavetBagi.olustur(self.grup, self.ozan, gun=7, max_kullanim=5)

        self.client.force_login(self.mert)
        yanit = self.client.post(
            reverse("groups:davet_ile_katil", args=[ham]), {"katilma_notu": "Merhaba"}
        )
        self.assertEqual(yanit.status_code, 200)

        uyelik = self.grup.uyelik(self.mert)
        self.assertEqual(uyelik.durum, Uyelik.Durum.BEKLIYOR)
        self.assertFalse(self.grup.uye_mi(self.mert))

        # Onaylanmadan grup içeriği görünmemeli.
        self.assertEqual(
            self.client.get(reverse("groups:detay", args=[self.grup.genel_id])).status_code,
            403,
        )

        # Yönetici onaylayınca açılmalı.
        self.client.force_login(self.ozan)
        self.client.post(
            reverse("groups:istek_karari", args=[self.grup.genel_id, uyelik.pk]),
            {"karar": "onayla"},
        )
        uyelik.refresh_from_db()
        self.assertEqual(uyelik.durum, Uyelik.Durum.ONAYLI)

        self.client.force_login(self.mert)
        self.assertEqual(
            self.client.get(reverse("groups:detay", args=[self.grup.genel_id])).status_code,
            200,
        )

    def test_suresi_dolmus_davet_calismaz(self):
        kayit, ham = DavetBagi.olustur(self.grup, self.ozan, gun=7, max_kullanim=5)
        kayit.son_kullanma = timezone.now() - timezone.timedelta(hours=1)
        kayit.save(update_fields=["son_kullanma"])

        self.client.force_login(self.mert)
        yanit = self.client.get(reverse("groups:davet_ile_katil", args=[ham]))
        self.assertEqual(yanit.status_code, 404)

    def test_uye_yonetici_yapamaz(self):
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.mert, durum=Uyelik.Durum.ONAYLI
        )
        uyelik = self.grup.uyelik(self.mert)

        self.client.force_login(self.mert)
        yanit = self.client.post(
            reverse("groups:rol_degistir", args=[self.grup.genel_id, uyelik.pk]),
            {"rol": "yonetici"},
        )
        self.assertEqual(yanit.status_code, 403)
        uyelik.refresh_from_db()
        self.assertEqual(uyelik.rol, Uyelik.Rol.UYE)

    def test_son_yonetici_indirilemez(self):
        self.client.force_login(self.ozan)
        uyelik = self.grup.uyelik(self.ozan)
        self.client.post(
            reverse("groups:rol_degistir", args=[self.grup.genel_id, uyelik.pk]),
            {"rol": "uye"},
        )
        uyelik.refresh_from_db()
        self.assertEqual(uyelik.rol, Uyelik.Rol.YONETICI)


class MacVePuanTesti(TestCase):
    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.mert = kullanici("mert@example.com", "Mert Arslan")
        self.burak = kullanici("burak@example.com", "Burak Yıldız")

        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        for kisi, rol in [
            (self.ozan, Uyelik.Rol.YONETICI),
            (self.mert, Uyelik.Rol.UYE),
            (self.burak, Uyelik.Rol.UYE),
        ]:
            Uyelik.objects.create(
                grup=self.grup, kullanici=kisi, rol=rol, durum=Uyelik.Durum.ONAYLI
            )

    def _oynanmis_mac(self):
        mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            konum="Ataşehir",
            olusturan=self.ozan,
        )
        for kisi in (self.ozan, self.mert, self.burak):
            Katilim.objects.create(mac=mac, kullanici=kisi, yanit=Katilim.Yanit.GELIYORUM)
        return mac

    def test_yonetici_mac_ekleyebilir(self):
        self.client.force_login(self.ozan)
        ileri = timezone.localtime(timezone.now() + timezone.timedelta(days=3))
        yanit = self.client.post(
            reverse("matches:olustur", args=[self.grup.genel_id]),
            {
                "baslangic": ileri.strftime("%Y-%m-%dT%H:%M"),
                "konum": "Ataşehir Spor Tesisleri",
                "sure_dakika": 60,
                "notlar": "",
                "yoklama_acik": "on",
                "yoklama_son": "",
            },
        )
        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(Mac.objects.count(), 1)

    def test_uye_mac_ekleyemez(self):
        self.client.force_login(self.mert)
        ileri = timezone.localtime(timezone.now() + timezone.timedelta(days=3))
        yanit = self.client.post(
            reverse("matches:olustur", args=[self.grup.genel_id]),
            {"baslangic": ileri.strftime("%Y-%m-%dT%H:%M"), "sure_dakika": 60},
        )
        self.assertEqual(yanit.status_code, 403)

    def test_gecmis_tarihe_mac_eklenebilir(self):
        """
        Unutulan maçlar sonradan girilebilmeli, eski maçlar arşivlenebilmeli.

        Eskiden form geçmiş tarihi reddediyordu. Yetki kontrolü zaten var:
        maç oluşturma görünümü yalnızca grup yöneticilerine açık.
        """
        self.client.force_login(self.ozan)
        geri = timezone.localtime(timezone.now() - timezone.timedelta(days=2))
        yanit = self.client.post(
            reverse("matches:olustur", args=[self.grup.genel_id]),
            {"baslangic": geri.strftime("%Y-%m-%dT%H:%M"), "sure_dakika": 60},
        )
        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(Mac.objects.count(), 1)
        self.assertTrue(Mac.objects.first().gecmis_mi)

    def test_uye_gecmise_de_mac_ekleyemez(self):
        """Geçmiş tarih serbestleşti diye yetki gevşemedi."""
        uye = kullanici("uye@example.com", "Sıradan Üye")
        Uyelik.objects.create(
            grup=self.grup, kullanici=uye, rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI
        )
        self.client.force_login(uye)
        geri = timezone.localtime(timezone.now() - timezone.timedelta(days=2))
        self.client.post(
            reverse("matches:olustur", args=[self.grup.genel_id]),
            {"baslangic": geri.strftime("%Y-%m-%dT%H:%M"), "sure_dakika": 60},
        )
        self.assertEqual(Mac.objects.count(), 0)

    def test_yoklama_son_tarihi_kontrolu_duruyor(self):
        """Geçmiş tarih serbestleşirken bu kural kaybolmamalı."""
        self.client.force_login(self.ozan)
        baslangic = timezone.localtime(timezone.now() + timezone.timedelta(days=3))
        sonra = baslangic + timezone.timedelta(days=1)
        yanit = self.client.post(
            reverse("matches:olustur", args=[self.grup.genel_id]),
            {
                "baslangic": baslangic.strftime("%Y-%m-%dT%H:%M"),
                "yoklama_son": sonra.strftime("%Y-%m-%dT%H:%M"),
                "sure_dakika": 60,
            },
        )
        self.assertEqual(yanit.status_code, 200)
        self.assertEqual(Mac.objects.count(), 0)

    def test_yoklama_oyu_kaydedilir(self):
        mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() + timezone.timedelta(days=2),
            olusturan=self.ozan,
        )
        self.client.force_login(self.mert)
        self.client.post(reverse("matches:yoklama_oyu", args=[mac.pk]), {"yanit": "geliyorum"})
        self.assertEqual(
            Katilim.objects.get(mac=mac, kullanici=self.mert).yanit,
            Katilim.Yanit.GELIYORUM,
        )

    def test_mac_detay_render_oluyor(self):
        mac = self._oynanmis_mac()
        self.client.force_login(self.ozan)
        yanit = self.client.get(reverse("matches:detay", args=[mac.pk]))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "Yoklama")

    def test_puanlama_kaydedilir_ve_ortalama_guncellenir(self):
        mac = self._oynanmis_mac()
        self.client.force_login(self.ozan)
        yanit = self.client.post(
            reverse("ratings:puanla", args=[mac.pk]),
            {f"puan_{self.mert.pk}": "8", f"puan_{self.burak.pk}": "6"},
        )
        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(Puan.objects.count(), 2)

        self.mert.profil.refresh_from_db()
        self.assertEqual(float(self.mert.profil.ortalama_puan), 8.0)
        self.assertEqual(self.mert.profil.puan_sayisi, 1)

    def test_kendine_puan_verilemez(self):
        mac = self._oynanmis_mac()
        self.client.force_login(self.ozan)
        self.client.post(
            reverse("ratings:puanla", args=[mac.pk]),
            {f"puan_{self.ozan.pk}": "10", f"puan_{self.mert.pk}": "7"},
        )
        self.assertFalse(Puan.objects.filter(puanlanan=self.ozan).exists())
        self.assertTrue(Puan.objects.filter(puanlanan=self.mert).exists())

    def test_macta_oynamayan_puanlayamaz(self):
        mac = self._oynanmis_mac()
        # Burak'ı kadrodan çıkar.
        Katilim.objects.filter(mac=mac, kullanici=self.burak).update(katildi=False)

        self.client.force_login(self.burak)
        yanit = self.client.post(
            reverse("ratings:puanla", args=[mac.pk]), {f"puan_{self.mert.pk}": "9"}
        )
        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(Puan.objects.count(), 0)

    def test_aralik_disi_puan_reddedilir(self):
        mac = self._oynanmis_mac()
        self.client.force_login(self.ozan)
        self.client.post(
            reverse("ratings:puanla", args=[mac.pk]), {f"puan_{self.mert.pk}": "15"}
        )
        self.assertEqual(Puan.objects.count(), 0)

    def test_puanlama_penceresi_sure_dolunca_kapanir(self):
        mac = self._oynanmis_mac()
        self.assertTrue(mac.puanlama_acik)

        mac.baslangic = timezone.now() - timezone.timedelta(
            days=settings.RATING_WINDOW_DAYS + 1
        )
        mac.save(update_fields=["baslangic"])
        self.assertFalse(mac.puanlama_acik)

        self.client.force_login(self.ozan)
        yanit = self.client.post(
            reverse("ratings:puanla", args=[mac.pk]), {f"puan_{self.mert.pk}": "9"}
        )
        self.assertEqual(yanit.status_code, 302)
        self.assertEqual(Puan.objects.count(), 0)

    def test_oy_vermeden_sonuclar_gizli(self):
        mac = self._oynanmis_mac()
        Puan.objects.create(mac=mac, puanlayan=self.ozan, puanlanan=self.mert, deger=9)

        self.client.force_login(self.burak)
        yanit = self.client.get(reverse("ratings:sonuclar", args=[mac.pk]))
        self.assertEqual(yanit.status_code, 200)
        self.assertFalse(yanit.context["gorunur"])

    def test_siralama_render_oluyor(self):
        mac = self._oynanmis_mac()
        Puan.objects.create(mac=mac, puanlayan=self.ozan, puanlanan=self.mert, deger=9)
        self.client.force_login(self.ozan)
        yanit = self.client.get(reverse("ratings:siralama", args=[self.grup.genel_id]))
        self.assertEqual(yanit.status_code, 200)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="halisaha-test-"))
class DosyaYuklemeGuvenligiTesti(TestCase):
    """Yükleme hattının kötü dosyaları gerçekten reddettiğini doğrular."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup,
            kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI,
            durum=Uyelik.Durum.ONAYLI,
        )
        self.mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            olusturan=self.ozan,
        )

    def test_gorsel_webp_olarak_yeniden_kodlanir(self):
        from apps.core.images import MAC_FOTOGRAFI, gorseli_isle
        from django.core.files.uploadedfile import SimpleUploadedFile

        ham = gorsel_uret()
        yuklenen = SimpleUploadedFile("mac.jpg", ham.read(), content_type="image/jpeg")
        icerik, ad = gorseli_isle(yuklenen, MAC_FOTOGRAFI)

        self.assertTrue(ad.endswith(".webp"))
        self.assertNotIn("mac", ad)  # kullanıcının verdiği ad kullanılmaz
        with Image.open(io.BytesIO(icerik.read())) as sonuc:
            self.assertEqual(sonuc.format, "WEBP")

    def test_gorsel_olmayan_dosya_reddedilir(self):
        from django.core.exceptions import ValidationError
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.core.images import MAC_FOTOGRAFI, gorseli_isle

        kotu = SimpleUploadedFile(
            "zararli.jpg", b"<?php system($_GET['c']); ?>", content_type="image/jpeg"
        )
        with self.assertRaises(ValidationError):
            gorseli_isle(kotu, MAC_FOTOGRAFI)

    def test_svg_reddedilir(self):
        from django.core.exceptions import ValidationError
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.core.images import MAC_FOTOGRAFI, gorseli_isle

        svg = SimpleUploadedFile(
            "xss.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            content_type="image/svg+xml",
        )
        with self.assertRaises(ValidationError):
            gorseli_isle(svg, MAC_FOTOGRAFI)

    @override_settings(MAX_UPLOAD_SIZE=1024)
    def test_cok_buyuk_dosya_reddedilir(self):
        from django.core.exceptions import ValidationError
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.core.images import MAC_FOTOGRAFI, gorseli_isle

        buyuk = SimpleUploadedFile("buyuk.jpg", b"x" * 4096, content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            gorseli_isle(buyuk, MAC_FOTOGRAFI)

    def test_uye_olmayan_fotografi_goremez(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.core.images import MAC_FOTOGRAFI, gorseli_isle
        from apps.matches.models import MacFotografi

        icerik, _ = gorseli_isle(
            SimpleUploadedFile("a.jpg", gorsel_uret().read(), content_type="image/jpeg"),
            MAC_FOTOGRAFI,
        )
        foto = MacFotografi(mac=self.mac, yukleyen=self.ozan)
        foto.dosya.save(icerik.name, icerik, save=False)
        foto.save()

        yabanci = kullanici("yabanci@example.com")
        self.client.force_login(yabanci)
        yanit = self.client.get(
            reverse("core:mac_fotografi", args=[foto.dosya_id])
        )
        self.assertEqual(yanit.status_code, 404)

        self.client.force_login(self.ozan)
        yanit = self.client.get(reverse("core:mac_fotografi", args=[foto.dosya_id]))
        self.assertEqual(yanit.status_code, 200)
        self.assertEqual(yanit["X-Content-Type-Options"], "nosniff")
        self.assertEqual(yanit["Content-Type"], "image/webp")
        # Windows'ta açık dosya silinemez; FileResponse'u kapatmadan
        # temizlik yapılamaz. Gerçek sunucuda bunu WSGI katmanı yapar.
        b"".join(yanit.streaming_content)
        yanit.close()


class SohbetGuvenligiTesti(TestCase):
    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.yabanci = kullanici("yabanci@example.com", "Yabancı")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup,
            kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI,
            durum=Uyelik.Durum.ONAYLI,
        )

    def test_uye_olmayan_sohbete_giremez(self):
        self.client.force_login(self.yabanci)
        yanit = self.client.get(reverse("chat:sohbet", args=[self.grup.genel_id]))
        self.assertEqual(yanit.status_code, 404)

        yanit = self.client.get(reverse("chat:api_durum", args=[self.grup.genel_id]))
        self.assertEqual(yanit.status_code, 404)

    def test_anahtar_kurulumu_render_oluyor(self):
        self.client.force_login(self.ozan)
        yanit = self.client.get(reverse("chat:anahtar_kurulumu"))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, "Şifreleme")

    def test_zayif_pbkdf2_reddedilir(self):
        self.client.force_login(self.ozan)
        yanit = self.client.post(
            reverse("chat:api_kendi_anahtarim"),
            data={
                "acik_anahtar": {"kty": "RSA", "n": "AQAB", "e": "AQAB", "alg": "RSA-OAEP-256"},
                "sifreli_ozel_anahtar": "AAAA",
                "tuz": "AAAA",
                "iv": "AAAA",
                "yineleme": 1000,
                "parmak_izi": "AAAA",
            },
            content_type="application/json",
        )
        self.assertEqual(yanit.status_code, 400)
        self.assertFalse(AnahtarCifti.objects.exists())

    def test_bozuk_base64_reddedilir(self):
        self.client.force_login(self.ozan)
        yanit = self.client.post(
            reverse("chat:api_kendi_anahtarim"),
            data={
                "acik_anahtar": {"kty": "RSA", "n": "AQAB", "e": "AQAB", "alg": "RSA-OAEP-256"},
                "sifreli_ozel_anahtar": "bu-base64-degil!!!",
                "tuz": "AAAA",
                "iv": "AAAA",
                "yineleme": 600000,
            },
            content_type="application/json",
        )
        self.assertEqual(yanit.status_code, 400)

    def test_gecerli_anahtar_kabul_edilir_ve_tekrari_reddedilir(self):
        self.client.force_login(self.ozan)
        govde = {
            "acik_anahtar": {"kty": "RSA", "n": "AQAB", "e": "AQAB", "alg": "RSA-OAEP-256"},
            "sifreli_ozel_anahtar": "AAAA",
            "tuz": "AAAA",
            "iv": "AAAA",
            "yineleme": 600000,
            "parmak_izi": "ABCD",
        }
        ilk = self.client.post(
            reverse("chat:api_kendi_anahtarim"), data=govde, content_type="application/json"
        )
        self.assertEqual(ilk.status_code, 200)
        self.assertTrue(AnahtarCifti.objects.filter(kullanici=self.ozan).exists())

        ikinci = self.client.post(
            reverse("chat:api_kendi_anahtarim"), data=govde, content_type="application/json"
        )
        self.assertEqual(ikinci.status_code, 409)

    def test_uye_cikarilinca_anahtar_dondurulur(self):
        from apps.chat.models import GrupAnahtari
        from apps.chat.services import aktif_anahtar

        mert = kullanici("mert@example.com", "Mert")
        uyelik = Uyelik.objects.create(
            grup=self.grup, kullanici=mert, durum=Uyelik.Durum.ONAYLI
        )
        GrupAnahtari.objects.create(
            grup=self.grup, surum=1, olusturan=self.ozan, aktif=True
        )

        self.client.force_login(self.ozan)
        self.client.post(reverse("groups:uye_cikar", args=[self.grup.genel_id, uyelik.pk]))

        self.assertIsNone(aktif_anahtar(self.grup))
        self.assertTrue(GrupAnahtari.objects.filter(grup=self.grup, dondurulmeli=True).exists())


class TumSayfalarRenderTesti(TestCase):
    """
    Dolu bir grupla her sayfayı gezer.

    Amaç şablon hatalarını (yanlış değişken adı, eksik url adı, bozuk filtre)
    tarayıcıyı açmadan yakalamak.
    """

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.mert = kullanici("mert@example.com", "Mert Arslan")
        self.aday = kullanici("aday@example.com", "Aday Oyuncu")

        self.grup = Grup.objects.create(
            ad="Perşembe Ekibi", aciklama="Her perşembe 21:00", kurucu=self.ozan
        )
        Uyelik.objects.create(
            grup=self.grup,
            kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI,
            durum=Uyelik.Durum.ONAYLI,
        )
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.mert, durum=Uyelik.Durum.ONAYLI
        )
        # Onay bekleyen bir istek: üyeler sayfasındaki karar bloğu da render olsun.
        Uyelik.objects.create(
            grup=self.grup,
            kullanici=self.aday,
            durum=Uyelik.Durum.BEKLIYOR,
            katilma_notu="Ozan'ın arkadaşıyım",
        )

        DavetBagi.olustur(self.grup, self.ozan, gun=7, max_kullanim=10, etiket="WhatsApp")

        self.gelecek_mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() + timezone.timedelta(days=3),
            konum="Ataşehir Spor Tesisleri",
            olusturan=self.ozan,
        )
        self.gecmis_mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            konum="Ataşehir Spor Tesisleri",
            olusturan=self.ozan,
        )
        for kisi in (self.ozan, self.mert):
            Katilim.objects.create(
                mac=self.gecmis_mac, kullanici=kisi, yanit=Katilim.Yanit.GELIYORUM
            )
        Katilim.objects.create(
            mac=self.gelecek_mac, kullanici=self.ozan, yanit=Katilim.Yanit.GELIYORUM
        )

        Puan.objects.create(
            mac=self.gecmis_mac, puanlayan=self.ozan, puanlanan=self.mert, deger=8
        )
        Puan.objects.create(
            mac=self.gecmis_mac, puanlayan=self.mert, puanlanan=self.ozan, deger=7
        )
        self.mert.profil.istatistikleri_yenile()
        self.ozan.profil.istatistikleri_yenile()

        from apps.notifications.models import Bildirim

        Bildirim.objects.create(
            alici=self.ozan,
            tur=Bildirim.Tur.KATILMA_ISTEGI,
            baslik="Aday Oyuncu gruba katılmak istiyor",
            mesaj="“Perşembe Ekibi” için yeni katılma isteği.",
            hedef_url=reverse("groups:uyeler", args=[self.grup.genel_id]),
        )

        self.client.force_login(self.ozan)

    def test_yoneticinin_gordugu_tum_sayfalar_200(self):
        gid = self.grup.genel_id
        yollar = [
            reverse("core:dashboard"),
            reverse("groups:liste"),
            reverse("groups:detay", args=[gid]),
            reverse("groups:duzenle", args=[gid]),
            reverse("groups:uyeler", args=[gid]),
            reverse("groups:davetler", args=[gid]),
            reverse("matches:liste", args=[gid]),
            reverse("matches:olustur", args=[gid]),
            reverse("matches:detay", args=[self.gelecek_mac.pk]),
            reverse("matches:detay", args=[self.gecmis_mac.pk]),
            reverse("matches:duzenle", args=[self.gecmis_mac.pk]),
            reverse("matches:kadro_duzenle", args=[self.gecmis_mac.pk]),
            reverse("ratings:puanla", args=[self.gecmis_mac.pk]),
            reverse("ratings:sonuclar", args=[self.gecmis_mac.pk]),
            reverse("ratings:siralama", args=[gid]),
            reverse("chat:sohbet", args=[gid]),
            reverse("chat:anahtar_kurulumu"),
            reverse("notifications:liste"),
            reverse("accounts:profil", args=[self.ozan.pk]),
            reverse("accounts:profil", args=[self.mert.pk]),
            reverse("accounts:profil_duzenle"),
        ]
        for yol in yollar:
            with self.subTest(yol=yol):
                yanit = self.client.get(yol)
                self.assertEqual(yanit.status_code, 200, f"{yol} → {yanit.status_code}")

    def test_normal_uye_yonetici_sayfalarini_goremez(self):
        self.client.force_login(self.mert)
        gid = self.grup.genel_id
        for yol in [
            reverse("groups:duzenle", args=[gid]),
            reverse("groups:davetler", args=[gid]),
            reverse("matches:olustur", args=[gid]),
            reverse("matches:kadro_duzenle", args=[self.gecmis_mac.pk]),
        ]:
            with self.subTest(yol=yol):
                self.assertEqual(self.client.get(yol).status_code, 403)

    def test_normal_uye_okuma_sayfalarini_gorebilir(self):
        self.client.force_login(self.mert)
        gid = self.grup.genel_id
        for yol in [
            reverse("groups:detay", args=[gid]),
            reverse("groups:uyeler", args=[gid]),
            reverse("matches:liste", args=[gid]),
            reverse("matches:detay", args=[self.gecmis_mac.pk]),
            reverse("ratings:siralama", args=[gid]),
            reverse("chat:sohbet", args=[gid]),
        ]:
            with self.subTest(yol=yol):
                self.assertEqual(self.client.get(yol).status_code, 200)

    def test_bekleyen_uye_hicbir_seyi_goremez(self):
        self.client.force_login(self.aday)
        gid = self.grup.genel_id
        self.assertEqual(
            self.client.get(reverse("groups:detay", args=[gid])).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("matches:detay", args=[self.gecmis_mac.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("chat:sohbet", args=[gid])).status_code, 404
        )

    def test_koyu_tema_da_render_oluyor(self):
        self.client.cookies["hst_tema"] = "koyu"
        yanit = self.client.get(reverse("core:dashboard"))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, 'data-tema="koyu"')


class MacSilmeTesti(TestCase):
    """Maç silme: yalnızca yönetici, yalnızca oynanmamış maç."""

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.mert = kullanici("mert@example.com", "Mert Ak")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.mert,
            rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI,
        )

    def _mac(self, gun_farki: int) -> Mac:
        return Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() + timezone.timedelta(days=gun_farki),
            olusturan=self.ozan,
        )

    def test_yonetici_oynanmamis_maci_silebilir(self):
        mac = self._mac(gun_farki=3)
        self.client.force_login(self.ozan)
        yanit = self.client.post(reverse("matches:sil", args=[mac.pk]))
        self.assertEqual(yanit.status_code, 302)
        self.assertFalse(Mac.objects.filter(pk=mac.pk).exists())

    def test_oynanmis_mac_da_silinebilir(self):
        """
        Yanlış girilmiş eski maçlar temizlenebilmeli.

        Bir dönem yalnızca gelecek maçlar silinebiliyordu; hatalı bir kayıt
        sonsuza kadar grubun geçmişinde kalıyordu.
        """
        mac = self._mac(gun_farki=-3)
        self.client.force_login(self.ozan)
        yanit = self.client.post(reverse("matches:sil", args=[mac.pk]))
        self.assertEqual(yanit.status_code, 302)
        self.assertFalse(Mac.objects.filter(pk=mac.pk).exists())

    def test_oynanmis_mac_silinince_puanlar_da_gidiyor(self):
        """Silinen maçın puanları ortalamalarda takılı kalmamalı."""
        mac = self._mac(gun_farki=-3)
        for kisi in (self.ozan, self.mert):
            Katilim.objects.create(
                mac=mac, kullanici=kisi, yanit=Katilim.Yanit.GELIYORUM, katildi=True
            )
        Puan.objects.create(mac=mac, puanlayan=self.ozan, puanlanan=self.mert, deger=8)

        self.client.force_login(self.ozan)
        self.client.post(reverse("matches:sil", args=[mac.pk]))

        self.assertFalse(Puan.objects.filter(mac_id=mac.pk).exists())
        self.mert.profil.refresh_from_db()
        self.assertEqual(self.mert.profil.puan_sayisi, 0)

    def test_uye_oynanmis_maci_silemez(self):
        """Geçmiş maçlar silinebilir oldu diye yetki gevşemedi."""
        mac = self._mac(gun_farki=-3)
        self.client.force_login(self.mert)
        self.client.post(reverse("matches:sil", args=[mac.pk]))
        self.assertTrue(Mac.objects.filter(pk=mac.pk).exists())

    def test_uye_maci_silemez(self):
        mac = self._mac(gun_farki=3)
        self.client.force_login(self.mert)
        self.client.post(reverse("matches:sil", args=[mac.pk]))
        self.assertTrue(Mac.objects.filter(pk=mac.pk).exists())

    def test_giris_yapmamis_silemez(self):
        mac = self._mac(gun_farki=3)
        self.client.post(reverse("matches:sil", args=[mac.pk]))
        self.assertTrue(Mac.objects.filter(pk=mac.pk).exists())


class IptalVeSilmeninPuanaEtkisiTesti(TestCase):
    """
    Silinen ya da iptal edilen maçın puanları ortalamalarda kalmamalı.

    Aksi hâlde şöyle bir yol açık olurdu: maçı kur, arkadaşlarından yüksek
    puan al, sonra maçı iptal et. Puanlar profilde kalır, maç görünmez.
    """

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.mert = kullanici("mert@example.com", "Mert Ak")
        self.burak = kullanici("burak@example.com", "Burak Yıl")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        for k, rol in [
            (self.ozan, Uyelik.Rol.YONETICI),
            (self.mert, Uyelik.Rol.UYE),
            (self.burak, Uyelik.Rol.UYE),
        ]:
            Uyelik.objects.create(
                grup=self.grup, kullanici=k, rol=rol, durum=Uyelik.Durum.ONAYLI
            )
        self.mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            olusturan=self.ozan,
        )
        for k in (self.ozan, self.mert, self.burak):
            Katilim.objects.create(
                mac=self.mac, kullanici=k, yanit=Katilim.Yanit.GELIYORUM, katildi=True
            )
        Puan.objects.create(mac=self.mac, puanlayan=self.ozan, puanlanan=self.mert, deger=9)
        Puan.objects.create(mac=self.mac, puanlayan=self.burak, puanlanan=self.mert, deger=9)

    def test_iptal_edilince_puanlar_silinir(self):
        self.client.force_login(self.ozan)
        self.client.post(reverse("matches:iptal_durumu", args=[self.mac.pk]))

        self.mac.refresh_from_db()
        self.assertTrue(self.mac.iptal)
        self.assertEqual(Puan.objects.filter(mac=self.mac).count(), 0)

        self.mert.profil.refresh_from_db()
        self.assertIsNone(self.mert.profil.ortalama_puan)
        self.assertEqual(self.mert.profil.puan_sayisi, 0)

    def test_iptal_edilen_mac_grup_siralamasina_girmez(self):
        from apps.ratings.hesaplar import grup_ozeti

        self.assertEqual(grup_ozeti(self.grup, self.mert)["adet"], 2)
        self.mac.iptal = True
        self.mac.save(update_fields=["iptal"])
        self.assertEqual(grup_ozeti(self.grup, self.mert)["adet"], 0)

    def test_mac_silinince_puanlar_da_gider(self):
        from apps.ratings.hesaplar import mac_puanlarini_sil

        mac_puanlarini_sil(self.mac)
        self.assertEqual(Puan.objects.filter(mac=self.mac).count(), 0)
        self.mert.profil.refresh_from_db()
        self.assertEqual(self.mert.profil.puan_sayisi, 0)


class GrupBazliPuanTesti(TestCase):
    """
    Puanlar gruplar arasında toplanmamalı.

    Senaryo: biri kendi "çiftlik" grubunu kurup oradan yüksek puan topluyor.
    Bu, asıl grubundaki ortalamasını etkilememeli.
    """

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.digerleri = [
            kullanici(f"o{i}@example.com", f"Oyuncu {i}") for i in range(4)
        ]

    def _grup_kur(self, ad, puan_degeri):
        grup = Grup.objects.create(ad=ad, kurucu=self.ozan)
        Uyelik.objects.create(
            grup=grup, kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        for k in self.digerleri:
            Uyelik.objects.create(
                grup=grup, kullanici=k, rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI
            )
        mac = Mac.objects.create(
            grup=grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            olusturan=self.ozan,
        )
        for k in [self.ozan, *self.digerleri]:
            Katilim.objects.create(
                mac=mac, kullanici=k, yanit=Katilim.Yanit.GELIYORUM, katildi=True
            )
        for k in self.digerleri:
            Puan.objects.create(
                mac=mac, puanlayan=k, puanlanan=self.ozan, deger=puan_degeri
            )
        return grup

    def test_ciftlik_grubu_asil_grubun_ortalamasini_etkilemez(self):
        from apps.ratings.hesaplar import grup_ozeti

        asil = self._grup_kur("Perşembe Ekibi", puan_degeri=6)
        ciftlik = self._grup_kur("Kendi Kurdugum Grup", puan_degeri=10)

        self.assertEqual(float(grup_ozeti(asil, self.ozan)["ortalama"]), 6.0)
        self.assertEqual(float(grup_ozeti(ciftlik, self.ozan)["ortalama"]), 10.0)

    def test_grup_siralamasi_yalnizca_kendi_maclarini_sayar(self):
        from apps.ratings.hesaplar import grup_siralamasi

        asil = self._grup_kur("Perşembe Ekibi", puan_degeri=6)
        self._grup_kur("Kendi Kurdugum Grup", puan_degeri=10)

        satirlar = grup_siralamasi(asil)
        ozan_satiri = next(s for s in satirlar if s["kullanici"].pk == self.ozan.pk)
        self.assertEqual(float(ozan_satiri["ortalama"]), 6.0)
        self.assertEqual(ozan_satiri["adet"], 4)

    def test_profilde_hicbir_puan_ortalamasi_gosterilmiyor(self):
        """
        Profil gruplar üstü bir sayfa; puan oraya ait değil.

        Ne küresel ortalama ne de grup kırılımı burada gösteriliyor. Bir
        oyuncunun bir gruptaki ortalaması yalnızca o grubun istatistik
        sayfasında görünüyor.
        """
        self._grup_kur("Perşembe Ekibi", puan_degeri=6)
        self.client.force_login(self.ozan)
        govde = self.client.get(
            reverse("accounts:profil", args=[self.ozan.pk])
        ).content.decode("utf-8")
        self.assertNotIn("Genel ortalama", govde)
        self.assertNotIn("Grup bazlı ortalamalar", govde)

    def test_grup_ortalamasi_istatistik_sayfasinda_duruyor(self):
        """Profilden kaldırıldı ama grup içinde hâlâ erişilebilir olmalı."""
        grup = self._grup_kur("Perşembe Ekibi", puan_degeri=6)
        self.client.force_login(self.ozan)
        govde = self.client.get(
            reverse("groups:uye_istatistik", args=[grup.genel_id, self.ozan.pk])
        ).content.decode("utf-8")
        self.assertIn("Grup içi ortalaması", govde)
        self.assertIn("6", govde)


class GorselBicimleriTesti(TestCase):
    """Yaygın telefon/kamera biçimleri kabul edilmeli."""

    @staticmethod
    def _yukleme(bicim: str, uzanti: str) -> SimpleUploadedFile:
        """Gerçek bir form yüklemesini taklit eder (size ve content_type gerekli)."""
        tampon = gorsel_uret(bicim=bicim)
        return SimpleUploadedFile(
            f"foto.{uzanti}", tampon.getvalue(), content_type=f"image/{uzanti}"
        )

    def test_yaygin_bicimler_kabul_edilir(self):
        from apps.core.images import AVATAR, gorseli_isle

        for bicim, uzanti in [("JPEG", "jpeg"), ("PNG", "png"), ("BMP", "bmp"),
                              ("TIFF", "tiff"), ("GIF", "gif"), ("WEBP", "webp")]:
            with self.subTest(bicim=bicim):
                icerik, ad = gorseli_isle(self._yukleme(bicim, uzanti), AVATAR)
                # Çıktı her zaman WEBP: girdi ne olursa olsun yeniden kodlanıyor.
                self.assertTrue(ad.endswith(".webp"))
                self.assertGreater(len(icerik.read()), 0)

    def test_heic_okuyucusu_kayitli(self):
        """iPhone fotoğrafları için pillow-heif kaydı yapılmış olmalı."""
        from PIL import Image

        from apps.core.images import HEIF_DESTEGI

        self.assertTrue(HEIF_DESTEGI, "pillow-heif kurulu değil")
        self.assertIn("HEIF", Image.registered_extensions().values())

    def test_heic_dosyasi_gercekten_islenebiliyor(self):
        """
        iPhone'dan gelen bir HEIC baştan sona geçmeli.

        Yalnızca "okuyucu kayıtlı mı" demek yetmiyor; asıl soru dosyanın
        çözülüp WEBP'ye kodlanabildiği.
        """
        from PIL import Image

        from apps.core.images import AVATAR, gorseli_isle

        ham = io.BytesIO()
        Image.new("RGB", (80, 60), (20, 120, 70)).save(ham, format="HEIF")
        ham.seek(0)

        yuklenen = SimpleUploadedFile("IMG_0421.HEIC", ham.getvalue(), content_type="image/heic")
        icerik, ad = gorseli_isle(yuklenen, AVATAR)

        self.assertTrue(ad.endswith(".webp"), "HEIC çıktısı WEBP olmalı")
        with Image.open(io.BytesIO(icerik.read())) as cikti:
            self.assertEqual(cikti.format, "WEBP")

    def test_buyuk_harfli_uzanti_kabul_edilir(self):
        """iPhone dosyaları .HEIC diye büyük harfle geliyor."""
        from apps.core.images import IZINLI_UZANTILAR, _uzanti

        self.assertIn(_uzanti("IMG_0421.HEIC"), IZINLI_UZANTILAR)
        self.assertIn(_uzanti("FOTO.JPG"), IZINLI_UZANTILAR)

    def test_dosya_secici_heic_gosteriyor(self):
        """
        Form <input accept="..."> ile doğrulama listesi ayrı düşmemeli.

        Ayrı düştüğünde arka uç HEIC'i kabul ediyor ama dosya seçicide
        HEIC dosyaları soluk görünüp seçilemiyordu.
        """
        from apps.accounts.forms import ProfilFormu
        from apps.core.images import DOSYA_SECICI_ACCEPT
        from apps.matches.forms import FotografFormu

        for parca in (".heic", ".heif", "image/heic"):
            self.assertIn(parca, DOSYA_SECICI_ACCEPT)

        self.assertIn(".heic", str(ProfilFormu()["avatar"]))
        self.assertIn(".heic", str(FotografFormu()["dosyalar"]))

    def test_desteklenmeyen_uzanti_reddedilir(self):
        from django.core.exceptions import ValidationError

        from apps.core.images import AVATAR, gorseli_isle

        # SVG içinde <script> taşıyabildiği için bilinçli olarak yasak.
        with self.assertRaises(ValidationError):
            gorseli_isle(self._yukleme("PNG", "svg"), AVATAR)

    def test_tarayicinin_bildirdigi_tur_engel_olmuyor(self):
        """
        content_type ne gelirse gelsin, geçerli bir görsel kabul edilmeli.

        Gerçek olay: Windows'ta ".jpeg" uzantısı "image/jpg" olarak
        bildiriliyordu ve sıradan bir fotoğraf "Bu dosya türü desteklenmiyor"
        diye reddediliyordu; aynı fotoğrafın ".jpg" hâli çalışıyordu.
        content_type istemciden geldiği için güvenlik değeri yok, yalnızca
        yanlış negatif üretiyordu.
        """
        from apps.core.images import AVATAR, gorseli_isle

        ham = gorsel_uret(bicim="JPEG").getvalue()
        for bildirilen in ["image/jpg", "image/pjpeg", "application/octet-stream",
                           "", "text/plain", "uydurma/tur"]:
            with self.subTest(content_type=bildirilen or "(bos)"):
                dosya = SimpleUploadedFile("foto.jpeg", ham, content_type=bildirilen)
                _, ad = gorseli_isle(dosya, AVATAR)
                self.assertTrue(ad.endswith(".webp"))

    def test_mpo_fotografi_kabul_edilir(self):
        """
        Çift kameralı telefonların ürettiği MPO dosyaları .jpeg uzantılı gelir.

        Pillow bunların format'ını "MPO" bildiriyor; beyaz listede olmadığı
        için telefondan çekilmiş sıradan bir fotoğraf reddediliyordu.
        """
        from PIL import Image

        from apps.core.images import AVATAR, gorseli_isle

        kare1 = Image.new("RGB", (90, 70), (20, 120, 70))
        kare2 = Image.new("RGB", (90, 70), (120, 20, 70))
        ham = io.BytesIO()
        kare1.save(ham, format="MPO", append_images=[kare2])
        ham.seek(0)

        # Gerçekten MPO ürettiğimizi doğrula, yoksa test bir şey kanıtlamaz.
        with Image.open(io.BytesIO(ham.getvalue())) as kontrol:
            self.assertEqual(kontrol.format, "MPO")

        dosya = SimpleUploadedFile("IMG_1234.jpeg", ham.getvalue(), content_type="image/jpeg")
        _, ad = gorseli_isle(dosya, AVATAR)
        self.assertTrue(ad.endswith(".webp"))

    def test_desteklenmeyen_bicim_mesaji_bicimi_soyluyor(self):
        """Hata mesajı hangi biçim olduğunu yazmalı; teşhis kolaylaşsın."""
        from django.core.exceptions import ValidationError

        from apps.core.images import AVATAR, gorseli_isle

        ham = io.BytesIO()
        Image.new("RGB", (40, 40), (10, 10, 10)).save(ham, format="PPM")
        dosya = SimpleUploadedFile("garip.png", ham.getvalue(), content_type="image/png")

        with self.assertRaises(ValidationError) as kutu:
            gorseli_isle(dosya, AVATAR)
        self.assertIn("PPM", str(kutu.exception))

    def test_gorsel_olmayan_dosya_hala_reddediliyor(self):
        """
        content_type kontrolü kalktı diye kapı açılmadı: asıl bekçi Pillow.

        Uzantısı ve bildirilen türü "doğru" olsa bile içerik görsel değilse
        reddedilmeli.
        """
        from django.core.exceptions import ValidationError

        from apps.core.images import AVATAR, gorseli_isle

        zararli = SimpleUploadedFile(
            "zararli.jpeg",
            b"<?php system($_GET['c']); ?>" + b"x" * 512,
            content_type="image/jpeg",
        )
        with self.assertRaises(ValidationError):
            gorseli_isle(zararli, AVATAR)


class _TakimliMacKurulumu(TestCase):
    """Takım/skor/puan testleri için ortak kurulum."""

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.oyuncular = [kullanici(f"o{i}@example.com", f"Oyuncu {i}") for i in range(10)]
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        for k in self.oyuncular:
            Uyelik.objects.create(
                grup=self.grup, kullanici=k, rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI
            )
        self.mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            olusturan=self.ozan,
        )
        self.herkes = [self.ozan, *self.oyuncular]
        for i, k in enumerate(self.herkes):
            Katilim.objects.create(
                mac=self.mac, kullanici=k,
                yanit=Katilim.Yanit.GELIYORUM, katildi=True,
                takim=Mac.Takim.A if i % 2 == 0 else Mac.Takim.B,
            )

    def _a_takimi(self):
        return [k for i, k in enumerate(self.herkes) if i % 2 == 0]

    def _b_takimi(self):
        return [k for i, k in enumerate(self.herkes) if i % 2 == 1]

    def _puanla(self, puanlanan, degerler):
        """Birden çok kişiden puan verdirir."""
        for veren, deger in degerler:
            Puan.objects.create(
                mac=self.mac, puanlayan=veren, puanlanan=puanlanan, deger=deger
            )


class KadroIsaretlemeTesti(TestCase):
    """
    Kadro kaydetmek işaretsiz oyuncuları "gelmiyor" yapmamalı.

    `Katilim.katildi` üç durumlu: True/False yönetici kararı, None ise karar
    yok ve oyuncunun kendi yoklama yanıtı geçerli. Kadro formu eskiden her
    kayıtta bu üçlüyü ikiliye indiriyor, yanıt vermemiş herkese "Yokum"
    yazıyordu.
    """

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        self.oyuncular = [kullanici(f"o{i}@example.com", f"Oyuncu {i}") for i in range(6)]
        for k in self.oyuncular:
            Uyelik.objects.create(
                grup=self.grup, kullanici=k,
                rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI,
            )
        self.mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() + timezone.timedelta(days=1),
            olusturan=self.ozan,
        )
        self.adres = reverse("matches:kadro_duzenle", args=[self.mac.pk])
        self.client.force_login(self.ozan)

    def _kaydet(self, oynayanlar, takimlar=None):
        veri = {"oynayan": [str(k.pk) for k in oynayanlar]}
        for k, takim in (takimlar or {}).items():
            veri[f"takim_{k.pk}"] = takim
        return self.client.post(self.adres, veri)

    def test_isaretsiz_oyuncuya_kayit_acilmiyor(self):
        """İlk taslak, yanıt vermemişleri "gelmiyor" yapmamalı."""
        self._kaydet(self.oyuncular[:2])

        self.assertEqual(Katilim.objects.filter(mac=self.mac).count(), 2)
        for k in self.oyuncular[2:]:
            self.assertFalse(
                Katilim.objects.filter(mac=self.mac, kullanici=k).exists(),
                "yanıt vermemiş oyuncuya kayıt açılmamalı",
            )

    def test_sonradan_eklenen_oyuncu_kadroya_giriyor(self):
        """Asıl şikâyet: ikinci turda işaretlenen oyuncu kadroya girmiyordu."""
        self._kaydet(self.oyuncular[:2])
        self._kaydet(self.oyuncular[:4])

        oynayanlar = self.mac.oynayan_kullanici_idleri()
        for k in self.oyuncular[:4]:
            self.assertIn(k.pk, oynayanlar, f"{k.gorunen_ad} kadroda olmalı")

        katilim = Katilim.objects.get(mac=self.mac, kullanici=self.oyuncular[3])
        self.assertTrue(katilim.katildi)
        self.assertEqual(katilim.yanit, Katilim.Yanit.GELIYORUM)

    def test_kac_kez_kaydedilirse_kaydedilsin_ayni_sonuc(self):
        for _ in range(4):
            self._kaydet(self.oyuncular[:3])

        self.assertEqual(Katilim.objects.filter(mac=self.mac).count(), 3)
        self.assertEqual(
            self.mac.oynayan_kullanici_idleri(),
            {k.pk for k in self.oyuncular[:3]},
        )

    def test_oyuncunun_kendi_yaniti_ezilmiyor(self):
        """Yoklamada 'Belki' diyen, kadroya alınmayınca 'Yokum' olmamalı."""
        Katilim.objects.create(
            mac=self.mac, kullanici=self.oyuncular[4], yanit=Katilim.Yanit.BELKI
        )
        self._kaydet(self.oyuncular[:2])

        katilim = Katilim.objects.get(mac=self.mac, kullanici=self.oyuncular[4])
        self.assertEqual(katilim.yanit, Katilim.Yanit.BELKI)
        self.assertIsNone(katilim.katildi, "karar yokken katildi None kalmalı")

    def test_geliyorum_diyenin_isareti_kaldirilabiliyor(self):
        """
        Kutunun işaretini kaldırmak hâlâ çalışmalı.

        'Geliyorum' diyen biri kendiliğinden işaretli geliyor; yönetici
        işareti kaldırdığında bu karar yanıtın önüne geçmeli, yoksa
        gelemeyen oyuncu kadrodan çıkarılamazdı.
        """
        gelen = self.oyuncular[5]
        Katilim.objects.create(
            mac=self.mac, kullanici=gelen, yanit=Katilim.Yanit.GELIYORUM
        )
        self.assertIn(gelen.pk, self.mac.oynayan_kullanici_idleri())

        self._kaydet(self.oyuncular[:2])

        katilim = Katilim.objects.get(mac=self.mac, kullanici=gelen)
        self.assertFalse(katilim.katildi)
        self.assertEqual(katilim.yanit, Katilim.Yanit.GELIYORUM, "yanıt korunmalı")
        self.assertNotIn(gelen.pk, self.mac.oynayan_kullanici_idleri())

    def test_kadrodan_cikarilanin_takimi_temizleniyor(self):
        self._kaydet(self.oyuncular[:2], {self.oyuncular[0]: "a", self.oyuncular[1]: "b"})
        self.assertEqual(
            Katilim.objects.get(mac=self.mac, kullanici=self.oyuncular[0]).takim, "a"
        )

        self._kaydet(self.oyuncular[1:2], {self.oyuncular[1]: "b"})
        self.assertEqual(
            Katilim.objects.get(mac=self.mac, kullanici=self.oyuncular[0]).takim, ""
        )

    def test_grup_disindaki_kimlik_yok_sayiliyor(self):
        yabanci = kullanici("yabanci@example.com", "Yabancı")
        self.client.post(self.adres, {"oynayan": [str(yabanci.pk)]})
        self.assertFalse(Katilim.objects.filter(mac=self.mac, kullanici=yabanci).exists())

    # --- Katılım listesine yansıma ------------------------------------
    #
    # Maç sayfasındaki katılım listesi ve sayaçlar yalnızca `yanit` alanına
    # bakıyor (bkz. Mac.sayim ve templates/matches/detay.html). Bu yüzden
    # aşağıdaki testler model alanlarına değil, sayfanın gösterdiğine bakıyor:
    # "işaretledim ama katılımda bir şey değişmedi" hatası ancak böyle
    # yakalanıyor.

    def _detay_govdesi(self):
        return self.client.get(
            reverse("matches:detay", args=[self.mac.pk])
        ).content.decode("utf-8")

    def test_isaretlemek_katilimi_hemen_degistiriyor(self):
        self._kaydet(self.oyuncular[:2])
        self.assertEqual(self.mac.sayim()["geliyorum"], 2)

    def test_ikinci_turda_isaretlenenlerin_katilimi_da_degisiyor(self):
        """
        Bildirilen hata: ilk kayıttan sonra işaretlemek katılımı değiştirmiyordu.

        Sebebi, kaydın yalnızca `katildi` alanını güncellemesiydi; katılım
        listesi `yanit`e baktığı için ekranda hiçbir şey olmuyordu.
        """
        self._kaydet(self.oyuncular[:2])
        self.assertEqual(self.mac.sayim()["geliyorum"], 2)

        self._kaydet(self.oyuncular[:4])
        self.assertEqual(self.mac.sayim()["geliyorum"], 4)

        self._kaydet(self.oyuncular[:6])
        self.assertEqual(self.mac.sayim()["geliyorum"], 6)

    def test_yokum_diyen_kadroya_alininca_geliyor_oluyor(self):
        """Yönetici kadroya aldıysa oyuncu oynuyordur; liste bunu göstermeli."""
        gelmeyecek = self.oyuncular[3]
        Katilim.objects.create(
            mac=self.mac, kullanici=gelmeyecek, yanit=Katilim.Yanit.YOKUM
        )
        self.assertEqual(self.mac.sayim()["yokum"], 1)

        self._kaydet([gelmeyecek])

        self.assertEqual(self.mac.sayim()["yokum"], 0)
        self.assertEqual(self.mac.sayim()["geliyorum"], 1)

    def test_ilk_kayitta_kimse_yok_olarak_isaretlenmiyor(self):
        """İkinci şikâyet: ilk taslak herkesi 'Yok' yapıyordu."""
        self._kaydet(self.oyuncular[:2])

        sayim = self.mac.sayim()
        self.assertEqual(sayim["yokum"], 0, "kimse 'Yok' olmamalı")
        self.assertEqual(sayim["geliyorum"], 2)
        self.assertEqual(sayim["yanitsiz"], 5, "kalanlar yanıtsız kalmalı")

        govde = self._detay_govdesi()
        self.assertNotIn(">Yok<", govde)
        self.assertIn("Yanıt yok", govde)


class AndroidUygulamasiTesti(TestCase):
    """
    Play Store'daki TWA için gereken iki herkese açık adres.

    assetlinks.json: Android adres çubuğunu ancak bu dosyada uygulamanın
    paket adını ve imza parmak izini bulursa gizliyor.
    /gizlilik/: Play, hesap açan uygulamalarda giriş gerektirmeyen bir
    gizlilik politikası adresi istiyor.
    """

    ADRES = "/.well-known/assetlinks.json"

    def test_ayar_bosken_gecerli_bos_json(self):
        """Parmak izi Play'e yüklemeden önce bilinmiyor; sayfa yine de çalışmalı."""
        with self.settings(ANDROID_PACKAGE_NAME="", ANDROID_SIGNING_FINGERPRINTS=[]):
            yanit = self.client.get(self.ADRES)

        self.assertEqual(yanit.status_code, 200)
        self.assertEqual(yanit["Content-Type"], "application/json")
        self.assertEqual(json.loads(yanit.content), [])

    def test_parmak_izi_verilince_dogru_yapida(self):
        parmak = "A1:B2:C3:D4:E5:F6:07:18:29:3A:4B:5C:6D:7E:8F:90:A1:B2:C3:D4:E5:F6:07:18:29:3A:4B:5C:6D:7E:8F:90"
        with self.settings(
            ANDROID_PACKAGE_NAME="site.halisahadefteri.twa",
            ANDROID_SIGNING_FINGERPRINTS=[parmak],
        ):
            veri = json.loads(self.client.get(self.ADRES).content)

        self.assertEqual(len(veri), 1)
        ifade = veri[0]
        self.assertEqual(
            ifade["relation"], ["delegate_permission/common.handle_all_urls"]
        )
        self.assertEqual(ifade["target"]["namespace"], "android_app")
        self.assertEqual(ifade["target"]["package_name"], "site.halisahadefteri.twa")
        self.assertEqual(ifade["target"]["sha256_cert_fingerprints"], [parmak])

    def test_birden_cok_parmak_izi(self):
        """Google'ın imzası ve kendi yükleme anahtarı birlikte bulunabilir."""
        with self.settings(
            ANDROID_PACKAGE_NAME="site.halisahadefteri.twa",
            ANDROID_SIGNING_FINGERPRINTS=["AA:BB", "CC:DD"],
        ):
            veri = json.loads(self.client.get(self.ADRES).content)

        self.assertEqual(veri[0]["target"]["sha256_cert_fingerprints"], ["AA:BB", "CC:DD"])

    def test_giris_gerektirmiyor(self):
        """Android bu dosyayı oturum açmadan okuyor."""
        self.assertEqual(self.client.get(self.ADRES).status_code, 200)

    def test_gizlilik_sayfasi_herkese_acik(self):
        yanit = self.client.get(reverse("core:gizlilik"))
        self.assertEqual(yanit.status_code, 200)

        govde = yanit.content.decode("utf-8")
        self.assertIn("Gizlilik politikası", govde)
        self.assertIn(settings.CONTACT_EMAIL, govde, "silme talebi için adres şart")
        self.assertIn("uçtan uca", govde.lower())

    def test_gizlilik_baglantisi_her_sayfada(self):
        govde = self.client.get(reverse("core:home")).content.decode("utf-8")
        self.assertIn(reverse("core:gizlilik"), govde)

    def test_robots_gizlilik_ve_wellknown_engellemiyor(self):
        govde = self.client.get("/robots.txt").content.decode("utf-8")
        self.assertIn("Allow: /gizlilik/", govde)
        self.assertIn("Allow: /.well-known/", govde)
        for satir in govde.splitlines():
            if satir.startswith("Disallow:"):
                yol = satir.split(":", 1)[1].strip()
                self.assertNotEqual(yol, "/", "tüm site taramaya kapatılmış")


class HesapSilmeTesti(TestCase):
    """
    Play Store, hesap açtıran uygulamalarda hesap silme yolu zorunlu tutuyor.

    Silme, kişinin kendi verisini götürmeli ama grubun ortak geçmişini
    (maçlar, fotoğraflar) götürmemeli; "oluşturan" alanları bu yüzden
    SET_NULL.
    """

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.mert = kullanici("mert@example.com", "Mert Öztürk")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.mert,
            rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI,
        )
        self.adres = reverse("accounts:hesabimi_sil")

    def test_sayfa_giris_gerektiriyor(self):
        self.assertEqual(self.client.get(self.adres).status_code, 302)

    def test_profil_ayarlarindan_ulasilabiliyor(self):
        self.client.force_login(self.mert)
        govde = self.client.get(
            reverse("accounts:profil_duzenle")
        ).content.decode("utf-8")
        self.assertIn(self.adres, govde)

    def test_eposta_yanlissa_silinmiyor(self):
        self.client.force_login(self.mert)
        self.client.post(self.adres, {"onay": "yanlis@example.com"})
        self.assertTrue(User.objects.filter(pk=self.mert.pk).exists())

    def test_eposta_dogruysa_siliniyor(self):
        mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            olusturan=self.ozan,
        )
        Katilim.objects.create(
            mac=mac, kullanici=self.mert, yanit=Katilim.Yanit.GELIYORUM, katildi=True
        )
        Puan.objects.create(mac=mac, puanlayan=self.mert, puanlanan=self.ozan, deger=7)

        self.client.force_login(self.mert)
        self.client.post(self.adres, {"onay": "mert@example.com"})

        self.assertFalse(User.objects.filter(pk=self.mert.pk).exists())
        self.assertFalse(Uyelik.objects.filter(kullanici_id=self.mert.pk).exists())
        self.assertFalse(Katilim.objects.filter(kullanici_id=self.mert.pk).exists())
        self.assertFalse(Puan.objects.filter(puanlayan_id=self.mert.pk).exists())

        # Grubun ortak geçmişi duruyor.
        self.assertTrue(Grup.objects.filter(pk=self.grup.pk).exists())
        self.assertTrue(Mac.objects.filter(pk=mac.pk).exists())

    def test_eposta_buyuk_harfle_de_kabul(self):
        self.client.force_login(self.mert)
        self.client.post(self.adres, {"onay": "MERT@EXAMPLE.COM"})
        self.assertFalse(User.objects.filter(pk=self.mert.pk).exists())

    def test_grubu_kuran_silinince_grup_kalmali(self):
        """Kurucu SET_NULL; kurucunun ayrılması grubu ve maçları silmemeli."""
        Uyelik.objects.filter(grup=self.grup, kullanici=self.mert).update(
            rol=Uyelik.Rol.YONETICI
        )
        self.client.force_login(self.ozan)
        self.client.post(self.adres, {"onay": "ozan@example.com"})

        self.grup.refresh_from_db()
        self.assertIsNone(self.grup.kurucu)
        self.assertEqual(self.grup.uye_sayisi, 1)

    def test_son_yonetici_once_yerine_birini_birakmali(self):
        """Tek yönetici çekilirse grup kilitlenir; silme engelleniyor."""
        self.client.force_login(self.ozan)

        govde = self.client.get(self.adres).content.decode("utf-8")
        self.assertIn("Perşembe Ekibi", govde)
        self.assertIn("tek yöneticisisin", govde)

        self.client.post(self.adres, {"onay": "ozan@example.com"})
        self.assertTrue(User.objects.filter(pk=self.ozan.pk).exists())

    def test_tek_kisilik_grubun_yoneticisi_silebiliyor(self):
        """Başka üyesi olmayan grup engel değil."""
        Uyelik.objects.filter(grup=self.grup, kullanici=self.mert).delete()
        self.client.force_login(self.ozan)
        self.client.post(self.adres, {"onay": "ozan@example.com"})
        self.assertFalse(User.objects.filter(pk=self.ozan.pk).exists())

    def test_gizlilik_sayfasi_silme_yolunu_gosteriyor(self):
        """Play, gizlilik politikasında silme yolunun yazılı olmasını istiyor."""
        govde = self.client.get(reverse("core:gizlilik")).content.decode("utf-8")
        self.assertIn(self.adres, govde)

    def test_hesap_silme_anlatimi_giris_gerektirmiyor(self):
        """
        Play Console'a verilen "Hesap silme URL'si" oturum açmadan
        açılabilmeli; Google'ın incelemecisi adresi doğrudan ziyaret ediyor.
        İşlemin kendisi giriş istiyor, anlatımı istememeli.
        """
        yanit = self.client.get(reverse("core:hesap_silme"))
        self.assertEqual(yanit.status_code, 200)

        govde = yanit.content.decode("utf-8")
        # Play'in aradığı üç şey.
        self.assertIn("Halısaha Defteri", govde, "uygulama adına atıf şart")
        self.assertIn("Hesabımı sil", govde, "adımlar belirgin olmalı")
        self.assertIn("14 gün", govde, "yedek saklama süresi yazmalı")
        self.assertIn("30 gün", govde, "güvenlik kaydı süresi yazmalı")
        # Silinen ve saklanan ayrımı.
        self.assertIn("Silinen veriler", govde)
        self.assertIn("Silinmeyen veriler", govde)

    def test_hesap_silme_sayfasi_isleme_yonlendiriyor(self):
        govde = self.client.get(reverse("core:hesap_silme")).content.decode("utf-8")
        self.assertIn(settings.CONTACT_EMAIL, govde, "giriş yapamayan için adres")
        self.assertIn(reverse("core:gizlilik"), govde)

    def test_herkese_acik_sayfalar_robots_ile_engellenmemis(self):
        govde = self.client.get("/robots.txt").content.decode("utf-8")
        for yol in ["/gizlilik/", "/kurallar/", "/hesap-silme/"]:
            self.assertIn(f"Allow: {yol}", govde)


class IcerikBildirmeTesti(TestCase):
    """
    Kullanıcı içeriğini bildirme ve yönetici incelemesi.

    Play, kullanıcı içeriği barındıran uygulamalarda kural + bildirme +
    kaldırma üçlüsünü birlikte arıyor.
    """

    def setUp(self):
        from apps.moderation.models import Sikayet

        self.Sikayet = Sikayet
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.mert = kullanici("mert@example.com", "Mert Öztürk")
        self.deniz = kullanici("deniz@example.com", "Deniz Uğurlu")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        for k in (self.mert, self.deniz):
            Uyelik.objects.create(
                grup=self.grup, kullanici=k,
                rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI,
            )
        self.mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            olusturan=self.ozan,
        )

    def _fotograf(self, yukleyen):
        from apps.matches.models import MacFotografi

        return MacFotografi.objects.create(
            mac=self.mac, yukleyen=yukleyen, dosya="maclar/test.webp"
        )

    def _mesaj(self, gonderen):
        from apps.chat.models import Mesaj

        return Mesaj.objects.create(
            grup=self.grup, gonderen=gonderen, anahtar_surum=1,
            sifreli_metin="c2lmcmVsaQ==", iv="aXY=",
        )

    # --- Fotoğraf ------------------------------------------------------
    def test_uye_baskasinin_fotografini_bildirebiliyor(self):
        foto = self._fotograf(self.deniz)
        self.client.force_login(self.mert)

        adres = reverse("moderation:fotograf_bildir", args=[foto.pk])
        self.assertEqual(self.client.get(adres).status_code, 200)

        self.client.post(adres, {"sebep": "mustehcen", "aciklama": "Uygunsuz"})

        sikayet = self.Sikayet.objects.get()
        self.assertEqual(sikayet.fotograf_id, foto.pk)
        self.assertEqual(sikayet.bildiren, self.mert)
        self.assertEqual(sikayet.durum, self.Sikayet.Durum.BEKLIYOR)

    def test_kendi_fotografini_bildiremiyor(self):
        """Kendi fotoğrafını zaten silebiliyor; bildirmenin anlamı yok."""
        foto = self._fotograf(self.mert)
        self.client.force_login(self.mert)
        self.client.post(
            reverse("moderation:fotograf_bildir", args=[foto.pk]), {"sebep": "spam"}
        )
        self.assertEqual(self.Sikayet.objects.count(), 0)

    def test_grup_disindaki_bildiremiyor(self):
        foto = self._fotograf(self.deniz)
        yabanci = kullanici("yabanci@example.com", "Yabancı")
        self.client.force_login(yabanci)
        yanit = self.client.get(reverse("moderation:fotograf_bildir", args=[foto.pk]))
        self.assertEqual(yanit.status_code, 403)

    def test_ayni_fotograf_iki_kez_bildirilemiyor(self):
        foto = self._fotograf(self.deniz)
        self.client.force_login(self.mert)
        adres = reverse("moderation:fotograf_bildir", args=[foto.pk])
        self.client.post(adres, {"sebep": "spam"})
        self.client.post(adres, {"sebep": "taciz"})
        self.assertEqual(self.Sikayet.objects.count(), 1)

    def test_gecersiz_sebep_kaydedilmiyor(self):
        foto = self._fotograf(self.deniz)
        self.client.force_login(self.mert)
        self.client.post(
            reverse("moderation:fotograf_bildir", args=[foto.pk]),
            {"sebep": "uydurma"},
        )
        self.assertEqual(self.Sikayet.objects.count(), 0)

    def test_yoneticiye_bildirim_gidiyor(self):
        from apps.notifications.models import Bildirim

        foto = self._fotograf(self.deniz)
        self.client.force_login(self.mert)
        self.client.post(
            reverse("moderation:fotograf_bildir", args=[foto.pk]), {"sebep": "siddet"}
        )
        self.assertTrue(
            Bildirim.objects.filter(
                alici=self.ozan, tur=Bildirim.Tur.ICERIK_BILDIRILDI
            ).exists()
        )

    # --- Sohbet mesajı -------------------------------------------------
    def test_mesaj_bildiriminde_metin_istemciden_geliyor(self):
        """
        Sunucu şifreli mesajı açamıyor; metin bildiren kişinin cihazından
        geliyor ve olduğu gibi saklanıyor.
        """
        mesaj = self._mesaj(self.deniz)
        self.client.force_login(self.mert)

        yanit = self.client.post(
            reverse("moderation:mesaj_bildir", args=[self.grup.genel_id]),
            data=json.dumps(
                {
                    "mesaj_id": mesaj.pk,
                    "sebep": "taciz",
                    "aciklama": "Hakaret etti",
                    "metin": "çözülmüş mesaj metni",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(yanit.status_code, 200)
        sikayet = self.Sikayet.objects.get()
        self.assertEqual(sikayet.mesaj_id, mesaj.pk)
        self.assertEqual(sikayet.mesaj_metni, "çözülmüş mesaj metni")
        self.assertEqual(sikayet.tur, self.Sikayet.Tur.MESAJ)

    def test_kendi_mesajini_bildiremiyor(self):
        mesaj = self._mesaj(self.mert)
        self.client.force_login(self.mert)
        yanit = self.client.post(
            reverse("moderation:mesaj_bildir", args=[self.grup.genel_id]),
            data=json.dumps({"mesaj_id": mesaj.pk, "sebep": "spam", "metin": "x"}),
            content_type="application/json",
        )
        self.assertEqual(yanit.status_code, 400)
        self.assertEqual(self.Sikayet.objects.count(), 0)

    # --- İnceleme ------------------------------------------------------
    def test_yonetici_fotografi_kaldirabiliyor(self):
        from apps.matches.models import MacFotografi

        foto = self._fotograf(self.deniz)
        self.client.force_login(self.mert)
        self.client.post(
            reverse("moderation:fotograf_bildir", args=[foto.pk]), {"sebep": "mustehcen"}
        )
        sikayet = self.Sikayet.objects.get()

        self.client.force_login(self.ozan)
        self.client.post(
            reverse("moderation:karar", args=[self.grup.genel_id, sikayet.pk]),
            {"islem": "kaldir"},
        )

        sikayet.refresh_from_db()
        self.assertEqual(sikayet.durum, self.Sikayet.Durum.KALDIRILDI)
        self.assertEqual(sikayet.inceleyen, self.ozan)
        self.assertFalse(MacFotografi.objects.filter(pk=foto.pk).exists())
        # İçerik gitse de şikâyet kaydı duruyor.
        self.assertIsNone(sikayet.fotograf_id)

    def test_yonetici_mesaji_sohbetten_cikarabiliyor(self):
        mesaj = self._mesaj(self.deniz)
        self.client.force_login(self.mert)
        self.client.post(
            reverse("moderation:mesaj_bildir", args=[self.grup.genel_id]),
            data=json.dumps({"mesaj_id": mesaj.pk, "sebep": "taciz", "metin": "x"}),
            content_type="application/json",
        )
        sikayet = self.Sikayet.objects.get()

        self.client.force_login(self.ozan)
        self.client.post(
            reverse("moderation:karar", args=[self.grup.genel_id, sikayet.pk]),
            {"islem": "kaldir"},
        )

        mesaj.refresh_from_db()
        self.assertTrue(mesaj.silindi)

    def test_reddedilen_bildirimde_icerik_duruyor(self):
        from apps.matches.models import MacFotografi

        foto = self._fotograf(self.deniz)
        self.client.force_login(self.mert)
        self.client.post(
            reverse("moderation:fotograf_bildir", args=[foto.pk]), {"sebep": "spam"}
        )
        sikayet = self.Sikayet.objects.get()

        self.client.force_login(self.ozan)
        self.client.post(
            reverse("moderation:karar", args=[self.grup.genel_id, sikayet.pk]),
            {"islem": "reddet"},
        )

        sikayet.refresh_from_db()
        self.assertEqual(sikayet.durum, self.Sikayet.Durum.REDDEDILDI)
        self.assertTrue(MacFotografi.objects.filter(pk=foto.pk).exists())

    def test_siradan_uye_inceleme_sayfasini_goremiyor(self):
        self.client.force_login(self.mert)
        yanit = self.client.get(reverse("moderation:liste", args=[self.grup.genel_id]))
        self.assertEqual(yanit.status_code, 403)

    def test_yonetici_bekleyenleri_goruyor(self):
        foto = self._fotograf(self.deniz)
        self.client.force_login(self.mert)
        self.client.post(
            reverse("moderation:fotograf_bildir", args=[foto.pk]),
            {"sebep": "mustehcen", "aciklama": "Uygunsuz görsel"},
        )

        self.client.force_login(self.ozan)
        govde = self.client.get(
            reverse("moderation:liste", args=[self.grup.genel_id])
        ).content.decode("utf-8")
        self.assertIn("Müstehcenlik", govde)
        self.assertIn("Uygunsuz görsel", govde)

    def test_grup_sayfasinda_bekleyen_sayisi(self):
        foto = self._fotograf(self.deniz)
        self.client.force_login(self.mert)
        self.client.post(
            reverse("moderation:fotograf_bildir", args=[foto.pk]), {"sebep": "spam"}
        )

        self.client.force_login(self.ozan)
        govde = self.client.get(
            reverse("groups:detay", args=[self.grup.genel_id])
        ).content.decode("utf-8")
        self.assertIn("bildirilen içerik", govde)

    # --- Kurallar sayfası ----------------------------------------------
    def test_kurallar_sayfasi_herkese_acik(self):
        yanit = self.client.get(reverse("core:kurallar"))
        self.assertEqual(yanit.status_code, 200)

        govde = yanit.content.decode("utf-8")
        for konu in ["Çıplaklık", "Şiddet", "Hakaret", "Bildir"]:
            self.assertIn(konu, govde)

    def test_kurallar_her_sayfanin_altinda(self):
        govde = self.client.get(reverse("core:home")).content.decode("utf-8")
        self.assertIn(reverse("core:kurallar"), govde)


class YonetimBaglantisiTesti(TestCase):
    """Yönetim paneli bağlantısı yalnızca nihai yöneticide görünmeli."""

    def setUp(self):
        self.adres = reverse("core:dashboard")

    def _govde(self, kisi):
        self.client.force_login(kisi)
        return self.client.get(self.adres).content.decode("utf-8")

    def test_nihai_yonetici_goruyor(self):
        nihai = kullanici("dev@example.com", "Nihai Yönetici")
        nihai.is_superuser = True
        nihai.is_staff = True
        nihai.save()
        self.assertIn("Yönetim paneli", self._govde(nihai))
        self.assertIn("/yonetim/", self._govde(nihai))

    def test_siradan_uye_gormuyor(self):
        self.assertNotIn("Yönetim paneli", self._govde(kullanici("a@example.com", "Ali")))

    def test_grup_yoneticisi_de_gormuyor(self):
        """Grup yöneticiliği Django yönetim arayüzüne erişim vermez."""
        yonetici = kullanici("y@example.com", "Grup Yöneticisi")
        grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=yonetici)
        Uyelik.objects.create(
            grup=grup, kullanici=yonetici,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        self.assertNotIn("Yönetim paneli", self._govde(yonetici))


class FormaGoluTesti(_TakimliMacKurulumu):
    """
    Forma golü: maçın ilk golü, skora yazılmaz, karşı takım forma giyer.

    Sonuçta yarım gol değerinde: yalnızca skor eşit bittiğinde maçı belirler.
    """

    def _kur(self, a, b, forma=""):
        self.mac.skor_a, self.mac.skor_b, self.mac.forma_golu = a, b, forma
        self.mac.save()
        return self.mac

    def test_beraberligi_forma_golu_bozuyor(self):
        mac = self._kur(3, 3, Mac.Takim.A)
        self.assertFalse(mac.berabere_mi)
        self.assertEqual(mac.kazanan_takim, Mac.Takim.A)
        self.assertTrue(mac.forma_golu_belirledi_mi)

    def test_bir_farkla_kaybeden_forma_golüyle_kazanamaz(self):
        """3-4 kaybeden takım forma golüyle maçı çeviremez (3.5 < 4)."""
        mac = self._kur(3, 4, Mac.Takim.A)
        self.assertEqual(mac.kazanan_takim, Mac.Takim.B)
        self.assertFalse(mac.forma_golu_belirledi_mi)

    def test_zaten_kazanan_takimda_sonuc_degismiyor(self):
        mac = self._kur(4, 3, Mac.Takim.A)
        self.assertEqual(mac.kazanan_takim, Mac.Takim.A)
        self.assertFalse(mac.forma_golu_belirledi_mi)

    def test_golsuz_macta_da_gecerli(self):
        """0-0: ilk golü atan yok gibi görünse de forma golü maçı bitirir."""
        mac = self._kur(0, 0, Mac.Takim.B)
        self.assertEqual(mac.kazanan_takim, Mac.Takim.B)
        self.assertTrue(mac.forma_golu_belirledi_mi)

    def test_forma_golu_yoksa_eski_davranis(self):
        mac = self._kur(3, 3)
        self.assertTrue(mac.berabere_mi)
        self.assertIsNone(mac.kazanan_takim)
        self.assertFalse(mac.forma_golu_belirledi_mi)

    def test_skor_yazisina_yansimiyor(self):
        """Yarım gol tabelada görünmez."""
        self.assertEqual(self._kur(3, 3, Mac.Takim.A).skor_yazisi, "3 - 3")

    def test_skor_girilmemisse_sayilmiyor(self):
        self.mac.forma_golu = Mac.Takim.A
        self.mac.save()
        self.assertFalse(self.mac.forma_golu_var_mi)
        self.assertIsNone(self.mac.kazanan_takim)

    def test_macin_adami_forma_golu_olan_takimdan(self):
        """Beraberlikte normalde iki takım da adaydı; forma golü daraltıyor."""
        from apps.ratings.denetim import macin_adami

        self._kur(3, 3, Mac.Takim.A)
        b_yildizi = self._b_takimi()[0]
        a_ikincisi = self._a_takimi()[1]
        self._puanla(b_yildizi, [(v, 10) for v in self._a_takimi()[:3]])
        self._puanla(a_ikincisi, [(v, 7) for v in self._b_takimi()[:3]])

        adamlar = macin_adami(self.mac)
        self.assertEqual([a["kullanici"].pk for a in adamlar], [a_ikincisi.pk])

    def test_forma_golu_olan_takim_bir_fazla_gol_girebiliyor(self):
        from apps.matches.views import _istatistik_tutarli_mi

        self._kur(3, 3, Mac.Takim.A)
        katilimlar = list(self.mac.oynayan_katilimlar())
        a_takimi = [k for k in katilimlar if k.takim == Mac.Takim.A]
        b_takimi = [k for k in katilimlar if k.takim == Mac.Takim.B]

        # A forma golüyle 4 gol girebilir, B yalnızca 3.
        a_takimi[0].gol = 4
        self.assertEqual(_istatistik_tutarli_mi(self.mac, katilimlar), "")

        a_takimi[0].gol = 5
        self.assertIn("en fazla 4", _istatistik_tutarli_mi(self.mac, katilimlar))

        a_takimi[0].gol = 0
        b_takimi[0].gol = 4
        self.assertIn("en fazla 3", _istatistik_tutarli_mi(self.mac, katilimlar))

    def test_kadro_formundan_kaydediliyor(self):
        self.client.force_login(self.ozan)
        veri = {"skor_a": "2", "skor_b": "2", "forma_golu": "b"}
        for k in self.herkes:
            veri[f"oynadi_{k.pk}"] = "1"
        veri["oynayan"] = [str(k.pk) for k in self.herkes]
        for i, k in enumerate(self.herkes):
            veri[f"takim_{k.pk}"] = "a" if i % 2 == 0 else "b"

        self.client.post(reverse("matches:kadro_duzenle", args=[self.mac.pk]), veri)
        self.mac.refresh_from_db()
        self.assertEqual(self.mac.forma_golu, "b")
        self.assertEqual(self.mac.kazanan_takim, Mac.Takim.B)

    def test_uydurma_deger_kabul_edilmiyor(self):
        self.client.force_login(self.ozan)
        veri = {"skor_a": "1", "skor_b": "1", "forma_golu": "c"}
        for k in self.herkes:
            veri[f"oynadi_{k.pk}"] = "1"
        veri["oynayan"] = [str(k.pk) for k in self.herkes]

        self.client.post(reverse("matches:kadro_duzenle", args=[self.mac.pk]), veri)
        self.mac.refresh_from_db()
        self.assertEqual(self.mac.forma_golu, "")


class DizilimGorseliTesti(_TakimliMacKurulumu):
    """Paylaşılabilir PNG: ölçüler, yetki ve puan gizleme."""

    def setUp(self):
        super().setUp()
        self.mac.skor_a, self.mac.skor_b = 2, 1
        self.mac.save()
        for sira, katilim in enumerate(self.mac.oynayan_katilimlar()):
            katilim.poz_x = 20 if katilim.takim == "a" else 80
            katilim.poz_y = 10 + sira * 8
            katilim.save()
        self.adres = reverse("matches:dizilim_gorseli", args=[self.mac.pk])

    def _boyut(self, icerik: bytes):
        import io

        from PIL import Image

        return Image.open(io.BytesIO(icerik)).size

    def test_yatay_ve_dikey_olculer(self):
        self.client.force_login(self.oyuncular[0])

        yatay = self.client.get(self.adres, {"yon": "yatay"})
        self.assertEqual(yatay.status_code, 200)
        self.assertEqual(yatay["Content-Type"], "image/png")
        self.assertEqual(self._boyut(yatay.content), (1920, 1080))

        dikey = self.client.get(self.adres, {"yon": "dikey"})
        self.assertEqual(self._boyut(dikey.content), (1080, 1920))

    def test_gecersiz_yon_yataya_dusuyor(self):
        self.client.force_login(self.oyuncular[0])
        yanit = self.client.get(self.adres, {"yon": "capraz"})
        self.assertEqual(self._boyut(yanit.content), (1920, 1080))

    def test_dosya_adi_ascii_ve_indirmeye_hazir(self):
        """
        Türkçe harf içeren grup adı dosya adına ASCII olarak geçmeli.

        Aksi hâlde Django başlığı RFC 2047 ile kodluyor ve tarayıcılar
        dosya adını bozuk gösteriyor.
        """
        yanit_basligi = None
        self.client.force_login(self.oyuncular[0])
        yanit_basligi = self.client.get(self.adres)["Content-Disposition"]

        self.assertIn("attachment", yanit_basligi)
        self.assertIn("persembe-ekibi", yanit_basligi)
        self.assertIn(".png", yanit_basligi)
        self.assertTrue(yanit_basligi.isascii())

    def test_grup_disindaki_goremiyor(self):
        yabanci = kullanici("yabanci@example.com", "Yabancı")
        self.client.force_login(yabanci)
        self.assertEqual(self.client.get(self.adres).status_code, 403)

    def test_giris_yapmayan_yonlendiriliyor(self):
        self.assertEqual(self.client.get(self.adres).status_code, 302)

    def test_puanlamayanin_gorselinde_puan_yok(self):
        """
        Görsel de sayfayla aynı kurala tabi.

        Piksel karşılaştırmak yerine iki görselin farklı olduğu kontrol
        ediliyor: puanları gören ile görmeyen aynı PNG'yi alamaz.
        """
        hedef = self._a_takimi()[1]
        for veren in self._b_takimi()[:3]:
            Puan.objects.create(mac=self.mac, puanlayan=veren, puanlanan=hedef, deger=9)

        izleyen = self.oyuncular[1]
        self.client.force_login(izleyen)
        gizli = self.client.get(self.adres).content

        for k in self.herkes:
            if k.pk != izleyen.pk:
                Puan.objects.update_or_create(
                    mac=self.mac, puanlayan=izleyen, puanlanan=k,
                    defaults={"deger": 6},
                )
        acik = self.client.get(self.adres).content

        self.assertNotEqual(gizli, acik, "puanlar görselde de gizlenmeli")

    def test_takimlar_kurulmamisken_de_cizilebiliyor(self):
        """Kadro yoksa çökmemeli; boş saha dönmeli."""
        self.mac.katilimlar.all().update(takim="")
        self.client.force_login(self.oyuncular[0])
        yanit = self.client.get(self.adres)
        self.assertEqual(yanit.status_code, 200)
        self.assertEqual(self._boyut(yanit.content), (1920, 1080))

    def test_dizilim_sayfasinda_dugme_ve_baglantilar(self):
        self.client.force_login(self.oyuncular[0])
        govde = self.client.get(
            reverse("matches:dizilim", args=[self.mac.pk])
        ).content.decode("utf-8")

        self.assertIn("data-gorsel-ac", govde)
        self.assertIn(f"{self.adres}?yon=yatay", govde)
        self.assertIn(f"{self.adres}?yon=dikey", govde)
        # Betik yüklenmese de indirilebilmeli.
        self.assertIn("download", govde)

    def test_duzenleme_ekraninda_dugme_yok(self):
        """Düzenlerken konumlar kaydedilmemiş olabilir; görsel yanıltıcı olur."""
        self.client.force_login(self.ozan)
        govde = self.client.get(
            reverse("matches:dizilim_duzenle", args=[self.mac.pk])
        ).content.decode("utf-8")
        self.assertNotIn("data-gorsel-ac", govde)

    def test_forma_golu_gorselde_yaziliyor(self):
        """Belirleyici forma golü görselde de görünmeli (piksel farkı)."""
        self.client.force_login(self.oyuncular[0])
        self.mac.skor_a = self.mac.skor_b = 2
        self.mac.save()
        formasiz = self.client.get(self.adres).content

        self.mac.forma_golu = Mac.Takim.A
        self.mac.save()
        formali = self.client.get(self.adres).content

        self.assertNotEqual(formasiz, formali)



class DizilimGorseliIsaretleriTesti(TestCase):
    """
    Görseldeki köşe işaretleri: yer ve çizim.

    Alfa testinde bulunan iki hata buradan korunuyor:
      * İşaretler profil fotoğrafının İÇİNE düşüyordu (sitede dışına oturuyor).
      * Asist işareti bomboş bir mavi daireydi; krampon hiç çizilmiyordu.

    Testler tek bir oyuncu kartını boş bir tuvale çizip pikselleri
    inceliyor. Tam görseli üretip karşılaştırmak, hatanın hangi işaretten
    geldiğini söylemiyordu.
    """

    ZEMIN = (0, 100, 0)  # tuval: hiçbir işaret rengiyle karışmayan yeşil
    MERKEZ = (200, 200)

    def setUp(self):
        self.kullanici = kullanici("isaret@example.com", "Ali Vural")

    # Hem telefon (dikey) hem bilgisayar (yatay) çıktısı sınanıyor: hata
    # ikisinde de vardı ve düzeltme ikisini de kapsamalı.
    YONLER = ("dikey", "yatay")

    def _olcu(self, yon="dikey"):
        from apps.matches.gorsel import _yerlesim

        return _yerlesim(yon)

    def _ciz(self, yon="dikey", **degisenler):
        """Tek oyuncu kartı çizer; (görsel, ölçü) döner."""
        from PIL import Image, ImageDraw

        from apps.matches.gorsel import _oyuncu_ciz

        oyuncu = {
            "kullanici": self.kullanici,
            "puan": 7.0,
            "puan_sinifi": "puan-mavi",
            "macin_adami": False,
            "gol": 0,
            "asist": 0,
            "kart": "",
            "kart_yazisi": "",
        }
        oyuncu.update(degisenler)

        olcu = self._olcu(yon)
        gorsel = Image.new("RGB", (400, 400), self.ZEMIN)
        ciz = ImageDraw.Draw(gorsel, "RGBA")
        # "b" takımı: diski koyu, dolayısıyla üstüne düşen açık renkli bir
        # işaret piksel olarak ayırt edilebiliyor.
        _oyuncu_ciz(gorsel, ciz, oyuncu, "b", self.MERKEZ, olcu)
        return gorsel, olcu

    def _degisen_pikseller(self, yon="dikey", **degisenler):
        """İşaret eklenince değişen piksellerin koordinatları."""
        temiz, olcu = self._ciz(yon)
        isaretli, _ = self._ciz(yon, **degisenler)

        farklar = []
        for x in range(400):
            for y in range(400):
                if temiz.getpixel((x, y)) != isaretli.getpixel((x, y)):
                    farklar.append((x, y))
        return farklar, olcu

    def _uzaklik(self, nokta):
        mx, my = self.MERKEZ
        return ((nokta[0] - mx) ** 2 + (nokta[1] - my) ** 2) ** 0.5

    # -- İşaretin yeri ----------------------------------------------------
    def _isaret_disarida_mi(self, ad: str, **degisenler):
        """
        Bir işaretin HER İKİ yönde de diskin dışında kaldığını doğrular.

        Hata telefonda da bilgisayarda da vardı. İşaret çizimi tek kod
        yolundan geçtiği için (`_oyuncu_ciz` yön parametresi almıyor)
        düzeltme ikisini birden kapsıyor; test bunu varsaymak yerine
        ölçüyor, çünkü iki yerleşimin yarıçapları farklı.
        """
        for yon in self.YONLER:
            with self.subTest(yon=yon):
                farklar, olcu = self._degisen_pikseller(yon, **degisenler)
                self.assertTrue(farklar, f"{ad} hiç çizilmemiş")

                yaricap = olcu.kart_yaricap
                iceride = [n for n in farklar if self._uzaklik(n) < yaricap * 0.75]
                self.assertEqual(
                    iceride, [],
                    f"{yon}: {ad} işaretinin {len(iceride)} pikseli "
                    "fotoğrafın içinde kalıyor",
                )

    def test_gol_isareti_diskin_disinda(self):
        """
        Gol topu profil fotoğrafının üstüne binmemeli.

        Alfa testinde bulunan hata: köşe işaretleri merkeze 0.72 yarıçap
        uzaklıkta çiziliyordu. Diskin yarıçapı 1.0 olduğu için hepsi
        fotoğrafın İÇİNDE kalıyordu; sitede ise fotoğrafın kenarına
        oturuyorlar.
        """
        self._isaret_disarida_mi("gol", gol=1)

    def test_asist_isareti_diskin_disinda(self):
        self._isaret_disarida_mi("asist", asist=1)

    def test_kart_isareti_diskin_disinda(self):
        self._isaret_disarida_mi("kart", kart="sari")

    def test_ikinci_sari_karti_diskin_disinda(self):
        """Bölünmüş kart en geniş kart türü; taşarsa önce o taşar."""
        self._isaret_disarida_mi("ikinci sarı", kart="ikinci-sari")

    def test_macin_adami_yildizi_diskin_disinda(self):
        self._isaret_disarida_mi("yıldız", macin_adami=True)

    def test_dort_isaret_birdenken_de_fotograf_temiz(self):
        """
        Canlıda bulunan en kötü durum: aynı oyuncuda kart, gol, asist ve
        yıldız birden. Dördü de fotoğrafın üstüne biniyordu.
        """
        self._isaret_disarida_mi(
            "dört işaret", kart="ikinci-sari", gol=3, asist=2, macin_adami=True
        )

    def test_isaretler_sitedeki_koselerde(self):
        """
        Yerleşim sitedeki dizilim tahtasıyla aynı olmalı:
            sol üst  kart        sağ üst  gol
            sol alt  yıldız      sağ alt  asist

        Aynı maça iki yerden bakınca farklı okunmamalı.
        """
        mx, my = self.MERKEZ
        beklenen = {
            "kart": (-1, -1),
            "gol": (+1, -1),
            "macin_adami": (-1, +1),
            "asist": (+1, +1),
        }
        for alan, (x_yon, y_yon) in beklenen.items():
            with self.subTest(isaret=alan):
                deger = "sari" if alan == "kart" else (True if alan == "macin_adami" else 1)
                farklar, _ = self._degisen_pikseller("dikey", **{alan: deger})
                orta_x = sum(n[0] for n in farklar) / len(farklar)
                orta_y = sum(n[1] for n in farklar) / len(farklar)
                self.assertEqual(
                    (1 if orta_x > mx else -1, 1 if orta_y > my else -1),
                    (x_yon, y_yon),
                    f"{alan} beklenen köşede değil",
                )

    # -- Asist kramponu ---------------------------------------------------
    def test_asist_dairesinin_icinde_krampon_var(self):
        """
        Asist işareti boş bir daire olmamalı.

        Alfa testinde bulunan hata: gol topla, kart dikdörtgenle, maçın
        adamı yıldızla anlatılırken asist yalnızca düz mavi bir noktaydı ve
        "işaret yüklenmemiş" gibi duruyordu. Sitede burada pas atan bir
        krampon var (gömülü SVG); görselde de aynısı çiziliyor.
        """
        from apps.matches.gorsel import _krampon_gorseli

        gorsel, olcu = self._ciz(asist=1)

        yaricap = olcu.kart_yaricap
        ax = self.MERKEZ[0] + yaricap * 1.08
        ay = self.MERKEZ[1] + yaricap * 0.92
        a_r = yaricap * 0.32

        # Dairenin içi (kenarlık hariç): krampon açık renkli, zemin koyu mavi.
        acik = 0
        for x in range(round(ax - a_r * 0.8), round(ax + a_r * 0.8) + 1):
            for y in range(round(ay - a_r * 0.8), round(ay + a_r * 0.8) + 1):
                r, g, b = gorsel.getpixel((x, y))
                if r > 170 and g > 170 and b > 170:
                    acik += 1

        self.assertGreater(
            acik, 8,
            "asist dairesi boş görünüyor; krampon çizilmemiş",
        )

        # Krampon görseli de kendi başına boş olmamalı.
        krampon = _krampon_gorseli(24, (246, 243, 234))
        dolu = sum(1 for piksel in krampon.getdata() if piksel[3] > 0)
        self.assertGreater(dolu, 40, "krampon görseli neredeyse boş")

    # -- Ad şeridi ---------------------------------------------------------
    def _serit_ustu(self, gorsel, olcu):
        """
        Ad şeridinin en üst pikselinin y değeri. Bulunamazsa None.

        Merkez sütunu taranıyor: yıldız solda, asist sağda duruyor, yani
        diskin altıyla şeridin arası bu sütunda temiz çim.

        Tarama diskin alt kenarının 5 piksel altından başlıyor. "b" takımının
        diski koyu (32, 34, 30) ve altında 3 piksellik bir gölge var; daha
        yukarıdan başlayınca şerit yerine bunlar yakalanıyordu.
        """
        mx, my = self.MERKEZ
        for y in range(my + olcu.kart_yaricap + 5, 400):
            r, g, b = gorsel.getpixel((mx, y))
            # Şerit (16, 26, 20, 220) yeşil zemine binince ~(14, 36, 17).
            if (r, g, b) != self.ZEMIN and r < 30 and g < 60 and b < 30:
                return y
        return None

    def test_ad_seridi_alt_isaretlerin_altinda(self):
        """
        Ad şeridi yıldıza ve asist rozetine binmemeli.

        İşaretler diskin dışına alınınca yıldızın alt ucu ve asist rozeti
        şeridin üst köşelerine değmeye başlamıştı. Şerit artık diskin değil,
        altına düşen işaretlerin en aşağısının altından başlıyor.
        """
        for yon in self.YONLER:
            with self.subTest(yon=yon):
                gorsel, olcu = self._ciz(yon, macin_adami=True, asist=2)
                serit = self._serit_ustu(gorsel, olcu)
                self.assertIsNotNone(serit, "ad şeridi bulunamadı")

                yaricap = olcu.kart_yaricap
                # Yıldızın en alt noktası: merkez + dikey sapma + yarıçapı.
                yildiz_alti = self.MERKEZ[1] + yaricap * 0.92 + yaricap * 0.40
                self.assertGreaterEqual(
                    serit, yildiz_alti,
                    f"{yon}: ad şeridi yıldızın üstüne biniyor",
                )

    def test_alt_isareti_olmayan_kart_uzamiyor(self):
        """
        Şerit yalnızca gerektiğinde aşağı iniyor.

        Bütün kartları uzatmak, birbirine yakın duran oyuncularda alttakinin
        diskiyle üsttekinin adının çakışması demekti; şerit tam da bu yüzden
        bir dönem tek satıra indirilmişti. Alt köşesinde işareti olmayan
        oyuncuda şerit eskisi gibi diske yakın durmalı.
        """
        for yon in self.YONLER:
            with self.subTest(yon=yon):
                sade, olcu = self._ciz(yon)
                yogun, _ = self._ciz(yon, macin_adami=True, asist=2)

                sade_y = self._serit_ustu(sade, olcu)
                yogun_y = self._serit_ustu(yogun, olcu)
                self.assertIsNotNone(sade_y)
                self.assertIsNotNone(yogun_y)

                self.assertLess(
                    sade_y, yogun_y,
                    "işaretsiz kart da gereksiz yere uzamış",
                )
                # Diskin hemen altında kalmalı, birkaç pikselden fazla değil.
                self.assertLessEqual(
                    sade_y - (self.MERKEZ[1] + olcu.kart_yaricap), 12
                )

    def test_ust_isaretler_seridi_asagi_itmiyor(self):
        """Gol ve kart üstte; şeridin yerini değiştirmemeleri gerekiyor."""
        for yon in self.YONLER:
            with self.subTest(yon=yon):
                sade, olcu = self._ciz(yon)
                ustlu, _ = self._ciz(yon, gol=3, kart="ikinci-sari")
                self.assertEqual(
                    self._serit_ustu(sade, olcu), self._serit_ustu(ustlu, olcu)
                )

    def test_krampon_kutusuna_sigdiriliyor(self):
        """
        Krampon, SVG kutusunun tamamına değil kendi sınırlarına göre
        ölçekleniyor.

        24x24'lük kutunun yalnızca alt yarısı dolu. Kutuyu kare olarak
        ölçekleyip daireye ortalayınca şekil aşağıda kalıyor, üstte
        kocaman bir boşluk oluşuyordu.
        """
        from apps.matches.gorsel import _krampon_gorseli

        krampon = _krampon_gorseli(40, (255, 255, 255))
        # Şekil basık ve geniş: yükseklik genişliğin yarısı kadar.
        self.assertLess(krampon.height, krampon.width)

        # Üst ve alt kenarda da boya olmalı; şekil kutuya oturmuş demektir.
        ust_satir = [krampon.getpixel((x, 0))[3] for x in range(krampon.width)]
        alt_satir = [
            krampon.getpixel((x, krampon.height - 1))[3]
            for x in range(krampon.width)
        ]
        self.assertTrue(any(a > 0 for a in ust_satir), "üstte boşluk kalmış")
        self.assertTrue(any(a > 0 for a in alt_satir), "altta boşluk kalmış")


class DizilimGorseliTemaTesti(_TakimliMacKurulumu):
    """
    Görselin teması, kişinin sitede kullandığı temayı izliyor.

    Koyu temada gezinirken açık zeminli bir görsel inince, indirilen şey
    bakılan şeye benzemiyordu. Saha her iki temada aynı yeşil kalıyor;
    sitede de `.saha` için koyu tema kuralı yok.
    """

    def setUp(self):
        super().setUp()
        self.mac.skor_a, self.mac.skor_b = 2, 1
        self.mac.save()
        for sira, katilim in enumerate(self.mac.oynayan_katilimlar()):
            katilim.poz_x = 20 if katilim.takim == "a" else 80
            katilim.poz_y = 10 + sira * 8
            katilim.save()
        self.adres = reverse("matches:dizilim_gorseli", args=[self.mac.pk])
        self.client.force_login(self.oyuncular[0])

    def _gorsel(self, **sorgu):
        import io

        from PIL import Image

        yanit = self.client.get(self.adres, sorgu)
        self.assertEqual(yanit.status_code, 200)
        return Image.open(io.BytesIO(yanit.content)).convert("RGB")

    def _zemin(self, gorsel):
        """Sol üst köşedeki kâğıt rengi (çerçevenin dışı)."""
        return gorsel.getpixel((4, 4))

    def test_acik_tema_kagit_zemin(self):
        r, g, b = self._zemin(self._gorsel(tema="acik"))
        self.assertGreater(min(r, g, b), 200, "açık temada zemin kâğıt olmalı")

    def test_koyu_tema_koyu_zemin(self):
        r, g, b = self._zemin(self._gorsel(tema="koyu"))
        self.assertLess(max(r, g, b), 60, "koyu temada zemin koyu olmalı")

    def test_tema_cerezden_okunuyor(self):
        """
        Kullanıcı ayrıca bir şey seçmeden, sitede kullandığı tema geçerli.

        Tema tercihi sunucu tarafında çerezden uygulanıyor
        (bkz. apps/core/context_processors.py); görsel de aynı yerden
        okuyor ki iki yer ayrışmasın.
        """
        from apps.core.context_processors import TEMA_COOKIE

        self.client.cookies[TEMA_COOKIE] = "koyu"
        r, g, b = self._zemin(self._gorsel())
        self.assertLess(max(r, g, b), 60, "çerezdeki koyu tema uygulanmadı")

        self.client.cookies[TEMA_COOKIE] = "acik"
        r, g, b = self._zemin(self._gorsel())
        self.assertGreater(min(r, g, b), 200, "çerezdeki açık tema uygulanmadı")

    def test_gecersiz_tema_aciga_dusuyor(self):
        self.client.cookies["hst_tema"] = "mor"
        r, g, b = self._zemin(self._gorsel(tema="parlak"))
        self.assertGreater(min(r, g, b), 200)

    def test_saha_iki_temada_da_ayni_yesil(self):
        """
        Çim temadan bağımsız. Sitede de öyle: `.saha` için koyu tema kuralı
        yok, değişen yalnızca sayfa kabuğu.
        """
        acik = self._gorsel(tema="acik")
        koyu = self._gorsel(tema="koyu")

        # Sahanın sol üst köşesinden içeri doğru bir nokta.
        from apps.matches.gorsel import _yerlesim

        olcu = _yerlesim("yatay")
        sol, ust, _, _ = olcu.saha_kutusu
        nokta = (sol + 12, ust + 12)

        self.assertEqual(acik.getpixel(nokta), koyu.getpixel(nokta))
        # Ve gerçekten yeşil olmalı.
        r, g, b = acik.getpixel(nokta)
        self.assertGreater(g, r)
        self.assertGreater(g, b)

    def test_koyu_tema_her_iki_yonde_de_calisiyor(self):
        for yon in ("yatay", "dikey"):
            with self.subTest(yon=yon):
                r, g, b = self._zemin(self._gorsel(yon=yon, tema="koyu"))
                self.assertLess(max(r, g, b), 60)


class TakimVeSkorTesti(_TakimliMacKurulumu):
    def test_skor_girilmeden_kazanan_yok(self):
        self.assertFalse(self.mac.skor_girildi_mi)
        self.assertIsNone(self.mac.kazanan_takim)

    def test_sifir_sifir_gecerli_bir_sonuc(self):
        """0-0 ile 'skor girilmedi' karıştırılmamalı."""
        self.mac.skor_a = 0
        self.mac.skor_b = 0
        self.mac.save()
        self.assertTrue(self.mac.skor_girildi_mi)
        self.assertTrue(self.mac.berabere_mi)
        self.assertIsNone(self.mac.kazanan_takim)

    def test_kazanan_dogru_belirleniyor(self):
        self.mac.skor_a, self.mac.skor_b = 5, 3
        self.mac.save()
        self.assertEqual(self.mac.kazanan_takim, Mac.Takim.A)

        self.mac.skor_a, self.mac.skor_b = 2, 6
        self.mac.save()
        self.assertEqual(self.mac.kazanan_takim, Mac.Takim.B)

    def test_yonetici_kadro_ve_skoru_kaydedebiliyor(self):
        self.client.force_login(self.ozan)
        veri = {"skor_a": "4", "skor_b": "2"}
        for k in self.herkes:
            veri.setdefault("oynayan", [])
        veri["oynayan"] = [str(k.pk) for k in self.herkes]
        for i, k in enumerate(self.herkes):
            veri[f"takim_{k.pk}"] = "a" if i % 2 == 0 else "b"

        yanit = self.client.post(
            reverse("matches:kadro_duzenle", args=[self.mac.pk]), veri
        )
        self.assertEqual(yanit.status_code, 302)
        self.mac.refresh_from_db()
        self.assertEqual((self.mac.skor_a, self.mac.skor_b), (4, 2))
        self.assertTrue(self.mac.takimlar_kurulmus_mu)

    def test_oynamayanin_takimi_temizleniyor(self):
        """Kadrodan çıkarılan oyuncunun eski takım ataması kalmamalı."""
        self.client.force_login(self.ozan)
        kalanlar = self.herkes[:-1]
        veri = {
            "oynayan": [str(k.pk) for k in kalanlar],
            "skor_a": "1", "skor_b": "1",
        }
        for i, k in enumerate(self.herkes):
            veri[f"takim_{k.pk}"] = "a" if i % 2 == 0 else "b"

        self.client.post(reverse("matches:kadro_duzenle", args=[self.mac.pk]), veri)
        cikarilan = Katilim.objects.get(mac=self.mac, kullanici=self.herkes[-1])
        self.assertEqual(cikarilan.takim, "")
        self.assertFalse(cikarilan.katildi)

    def test_uye_kadro_duzenleyemiyor(self):
        self.client.force_login(self.oyuncular[0])
        yanit = self.client.post(
            reverse("matches:kadro_duzenle", args=[self.mac.pk]),
            {"oynayan": [], "skor_a": "9", "skor_b": "0"},
        )
        self.assertEqual(yanit.status_code, 403)
        self.mac.refresh_from_db()
        self.assertIsNone(self.mac.skor_a)


class MacinAdamiTesti(_TakimliMacKurulumu):
    def test_kazanan_takimin_en_iyisi_secilir(self):
        from apps.ratings.denetim import macin_adami

        self.mac.skor_a, self.mac.skor_b = 5, 1
        self.mac.save()

        # B takımından biri daha yüksek puan alsa bile kazanan A'dan seçilmeli.
        a_yildizi = self._a_takimi()[1]
        b_yildizi = self._b_takimi()[0]
        self._puanla(a_yildizi, [(v, 8) for v in self._b_takimi()[:3]])
        self._puanla(b_yildizi, [(v, 10) for v in self._a_takimi()[:3]])

        adamlar = macin_adami(self.mac)
        self.assertEqual([a["kullanici"].pk for a in adamlar], [a_yildizi.pk])

    def test_beraberlikte_iki_takimdan_en_iyisi(self):
        from apps.ratings.denetim import macin_adami

        self.mac.skor_a, self.mac.skor_b = 3, 3
        self.mac.save()

        b_yildizi = self._b_takimi()[0]
        self._puanla(self._a_takimi()[1], [(v, 7) for v in self._b_takimi()[:3]])
        self._puanla(b_yildizi, [(v, 9) for v in self._a_takimi()[:3]])

        adamlar = macin_adami(self.mac)
        self.assertEqual([a["kullanici"].pk for a in adamlar], [b_yildizi.pk])

    def test_esitlikte_yildiz_paylasilir(self):
        from apps.ratings.denetim import macin_adami

        self.mac.skor_a, self.mac.skor_b = 4, 0
        self.mac.save()

        birinci, ikinci = self._a_takimi()[1], self._a_takimi()[2]
        self._puanla(birinci, [(v, 9) for v in self._b_takimi()[:3]])
        self._puanla(ikinci, [(v, 9) for v in self._b_takimi()[:3]])

        adamlar = macin_adami(self.mac)
        self.assertEqual(len(adamlar), 2)

    def test_skor_girilmemisse_macin_adami_yok(self):
        from apps.ratings.denetim import macin_adami

        self._puanla(self._a_takimi()[1], [(v, 9) for v in self._b_takimi()[:3]])
        self.assertEqual(macin_adami(self.mac), [])

    def test_karantinadaki_puan_macin_adamini_belirlemez(self):
        from apps.ratings.denetim import macin_adami

        self.mac.skor_a, self.mac.skor_b = 4, 0
        self.mac.save()

        sahte_yildiz = self._a_takimi()[1]
        gercek = self._a_takimi()[2]
        self._puanla(sahte_yildiz, [(v, 10) for v in self._b_takimi()[:3]])
        Puan.objects.filter(puanlanan=sahte_yildiz).update(karantinada=True)
        self._puanla(gercek, [(v, 7) for v in self._b_takimi()[:3]])

        adamlar = macin_adami(self.mac)
        self.assertEqual([a["kullanici"].pk for a in adamlar], [gercek.pk])


class OyDenetimiTesti(_TakimliMacKurulumu):
    """Herkese aynı puanı vererek ortalamaları çarpıtmaya karşı koruma."""

    def _oy_ver(self, veren, deger_uretici):
        hedefler = [k for k in self.herkes if k.pk != veren.pk]
        for hedef in hedefler:
            Puan.objects.create(
                mac=self.mac, puanlayan=veren,
                puanlanan=hedef, deger=deger_uretici(hedef),
            )
        return len(hedefler)

    def test_herkese_10_verilirse_puanlar_siliniyor(self):
        from apps.ratings.denetim import mac_oylarini_denetle

        veren = self.oyuncular[0]
        adet = self._oy_ver(veren, lambda k: 10)
        self.assertGreaterEqual(adet, 10)

        sonuc = mac_oylarini_denetle(self.mac, veren)
        self.assertEqual(sonuc.karar, "bariz")
        self.assertEqual(Puan.objects.filter(puanlayan=veren).count(), 0)

    def test_herkese_1_verilirse_puanlar_siliniyor(self):
        from apps.ratings.denetim import mac_oylarini_denetle

        veren = self.oyuncular[0]
        self._oy_ver(veren, lambda k: 1)
        self.assertEqual(mac_oylarini_denetle(self.mac, veren).karar, "bariz")
        self.assertEqual(Puan.objects.filter(puanlayan=veren).count(), 0)

    def test_herkese_7_verilirse_silinmiyor_karantinaya_aliniyor(self):
        """Uç olmayan tek düze oy silinmez: masum olabilir, yönetici karar verir."""
        from apps.ratings.denetim import mac_oylarini_denetle

        veren = self.oyuncular[0]
        adet = self._oy_ver(veren, lambda k: 7)

        sonuc = mac_oylarini_denetle(self.mac, veren)
        self.assertEqual(sonuc.karar, "supheli")
        self.assertEqual(Puan.objects.filter(puanlayan=veren).count(), adet)
        self.assertEqual(
            Puan.objects.filter(puanlayan=veren, karantinada=True).count(), adet
        )

    def test_normal_dagilim_dokunulmadan_geciyor(self):
        from apps.ratings.denetim import mac_oylarini_denetle

        veren = self.oyuncular[0]
        degerler = iter([6, 8, 5, 9, 7, 10, 4, 8, 6, 7])
        adet = self._oy_ver(veren, lambda k: next(degerler))

        sonuc = mac_oylarini_denetle(self.mac, veren)
        self.assertEqual(sonuc.karar, "temiz")
        self.assertEqual(
            Puan.objects.filter(puanlayan=veren, karantinada=False).count(), adet
        )

    def test_az_sayida_oy_denetlenmiyor(self):
        """Üç kişiye 10 vermek istatistiksel olarak bir şey ifade etmiyor."""
        from apps.ratings.denetim import mac_oylarini_denetle

        veren = self.oyuncular[0]
        for hedef in self.oyuncular[1:4]:
            Puan.objects.create(
                mac=self.mac, puanlayan=veren, puanlanan=hedef, deger=10
            )
        self.assertEqual(mac_oylarini_denetle(self.mac, veren).karar, "temiz")
        self.assertEqual(Puan.objects.filter(puanlayan=veren).count(), 3)

    def test_karantinadaki_puan_ortalamaya_girmiyor(self):
        from apps.ratings.denetim import mac_oylarini_denetle
        from apps.ratings.hesaplar import grup_ozeti

        hedef = self.oyuncular[1]
        # Önce dürüst oylar
        self._puanla(hedef, [(v, 6) for v in self.oyuncular[2:6]])
        oncesi = grup_ozeti(self.grup, hedef)["ortalama"]

        # Sonra şişirmeye çalışan biri
        veren = self.oyuncular[0]
        self._oy_ver(veren, lambda k: 7)
        mac_oylarini_denetle(self.mac, veren)

        self.assertEqual(grup_ozeti(self.grup, hedef)["ortalama"], oncesi)

    def test_yoneticiye_bildirim_gidiyor(self):
        from apps.notifications.models import Bildirim
        from apps.ratings.denetim import mac_oylarini_denetle

        veren = self.oyuncular[0]
        self._oy_ver(veren, lambda k: 10)
        mac_oylarini_denetle(self.mac, veren)

        self.assertTrue(
            Bildirim.objects.filter(
                alici=self.ozan, tur=Bildirim.Tur.SUPHELI_OYLAMA
            ).exists()
        )
        # Oy veren de bilgilendirilmeli.
        self.assertTrue(
            Bildirim.objects.filter(
                alici=veren, tur=Bildirim.Tur.PUANLARIN_SILINDI
            ).exists()
        )

    def test_yonetici_karantinayi_serbest_birakabiliyor(self):
        from apps.ratings.denetim import karantinayi_coz, mac_oylarini_denetle
        from apps.ratings.hesaplar import grup_ozeti

        veren = self.oyuncular[0]
        adet = self._oy_ver(veren, lambda k: 7)
        mac_oylarini_denetle(self.mac, veren)

        cozulen = karantinayi_coz(self.mac, veren, sil=False)
        self.assertEqual(cozulen, adet)
        self.assertEqual(
            Puan.objects.filter(puanlayan=veren, karantinada=True).count(), 0
        )
        # Artık ortalamalara katılıyor.
        hedef = [k for k in self.herkes if k.pk != veren.pk][0]
        self.assertIsNotNone(grup_ozeti(self.grup, hedef)["ortalama"])

    def test_yonetici_karantinayi_silebiliyor(self):
        from apps.ratings.denetim import karantinayi_coz, mac_oylarini_denetle

        veren = self.oyuncular[0]
        self._oy_ver(veren, lambda k: 7)
        mac_oylarini_denetle(self.mac, veren)

        karantinayi_coz(self.mac, veren, sil=True)
        self.assertEqual(Puan.objects.filter(puanlayan=veren).count(), 0)

    def test_inceleme_sayfasi_uyeye_kapali(self):
        self.client.force_login(self.oyuncular[0])
        yanit = self.client.get(
            reverse("ratings:oy_incelemesi", args=[self.grup.genel_id])
        )
        self.assertEqual(yanit.status_code, 403)

    def test_inceleme_sayfasi_yoneticiye_acik(self):
        from apps.ratings.denetim import mac_oylarini_denetle

        veren = self.oyuncular[0]
        self._oy_ver(veren, lambda k: 7)
        mac_oylarini_denetle(self.mac, veren)

        self.client.force_login(self.ozan)
        yanit = self.client.get(
            reverse("ratings:oy_incelemesi", args=[self.grup.genel_id])
        )
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, veren.gorunen_ad)


class PuanRengiTesti(TestCase):
    """Maç puanı rozetinin renk ölçeği."""

    def test_olcek_dogru_esleniyor(self):
        from apps.matches.dizilim import puan_rengi

        # Ölçeğin ortası 5-6 bandı (sarı). Sınır değerleri de kontrol
        # ediliyor: aralıklar üst sınır dışta, yani 5.0 sarı, 4.9 kırmızı.
        beklenen = [
            (0.0, "puan-siyah"),
            (2.9, "puan-siyah"),
            (3.0, "puan-kirmizi"),
            (4.9, "puan-kirmizi"),
            (5.0, "puan-sari"),
            (5.9, "puan-sari"),
            (6.0, "puan-yesil"),
            (6.9, "puan-yesil"),
            (7.0, "puan-mavi"),
            (7.9, "puan-mavi"),
            (8.0, "puan-lacivert"),
            (8.9, "puan-lacivert"),
            (9.0, "puan-mor"),
            (9.4, "puan-mor"),
            (10.0, "puan-mor"),
        ]
        for deger, sinif in beklenen:
            with self.subTest(puan=deger):
                self.assertEqual(puan_rengi(deger), sinif)

    def test_olcekte_bosluk_yok(self):
        """Her puan tam olarak bir renge denk gelmeli."""
        from apps.matches.dizilim import puan_rengi

        deger = 0.0
        while deger <= 10.0:
            with self.subTest(puan=round(deger, 1)):
                self.assertNotEqual(
                    puan_rengi(round(deger, 1)), "", f"{deger} bir renge denk gelmiyor"
                )
            deger += 0.1

    def test_bes_ortalama_olarak_tanimli(self):
        """Arayüzdeki '5 ortalamadır' açıklaması bu sabitten besleniyor."""
        from apps.matches.dizilim import ORTALAMA_PUAN

        self.assertEqual(ORTALAMA_PUAN, 5)

    def test_puansiz_oyuncuda_renk_yok(self):
        from apps.matches.dizilim import puan_rengi

        self.assertEqual(puan_rengi(None), "")


class DizilimTesti(_TakimliMacKurulumu):
    def test_dizilim_mac_oynanmadan_da_acilabiliyor(self):
        """
        Yönetici takımları ve dizilimi maçtan ÖNCE kurabilmeli.

        Eskiden bu sayfa yalnızca oynanmış maçlarda açılıyordu; planlama
        yapılamıyordu. Puan rozetleri doğal olarak boş görünür.
        """
        gelecek = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() + timezone.timedelta(days=2),
            olusturan=self.ozan,
        )
        for i, k in enumerate(self.herkes):
            Katilim.objects.create(
                mac=gelecek, kullanici=k, yanit=Katilim.Yanit.GELIYORUM,
                katildi=True, takim="a" if i % 2 == 0 else "b",
            )

        self.client.force_login(self.ozan)
        self.assertEqual(
            self.client.get(reverse("matches:dizilim", args=[gelecek.pk])).status_code, 200
        )
        self.assertEqual(
            self.client.get(
                reverse("matches:dizilim_duzenle", args=[gelecek.pk])
            ).status_code,
            200,
        )

    def test_oynanmamis_macta_kadro_duzenlenebiliyor(self):
        gelecek = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() + timezone.timedelta(days=2),
            olusturan=self.ozan,
        )
        self.client.force_login(self.ozan)
        yanit = self.client.post(
            reverse("matches:kadro_duzenle", args=[gelecek.pk]),
            {
                "oynayan": [str(k.pk) for k in self.herkes],
                **{
                    f"takim_{k.pk}": ("a" if i % 2 == 0 else "b")
                    for i, k in enumerate(self.herkes)
                },
            },
        )
        self.assertEqual(yanit.status_code, 302)
        self.assertTrue(gelecek.takimlar_kurulmus_mu)

    def test_uye_dizilimi_gorebiliyor(self):
        self.client.force_login(self.oyuncular[0])
        yanit = self.client.get(reverse("matches:dizilim", args=[self.mac.pk]))
        self.assertEqual(yanit.status_code, 200)
        self.assertContains(yanit, 'id="saha"')

    def test_uye_dizilimi_duzenleyemiyor(self):
        self.client.force_login(self.oyuncular[0])
        yanit = self.client.get(reverse("matches:dizilim_duzenle", args=[self.mac.pk]))
        self.assertEqual(yanit.status_code, 403)

    def test_yerlestirilmemis_oyuncuya_varsayilan_konum_veriliyor(self):
        """Yönetici boş sahayla değil, düzeltilecek bir dizilimle başlamalı."""
        from apps.matches.dizilim import dizilim_verisi

        takimlar = dizilim_verisi(self.mac)
        for takim in takimlar:
            for oyuncu in takim["oyuncular"]:
                self.assertIsNotNone(oyuncu["x"])
                self.assertIsNotNone(oyuncu["y"])
                self.assertTrue(0 <= oyuncu["x"] <= 100)
                self.assertTrue(0 <= oyuncu["y"] <= 100)

    def test_takimlar_sahanin_iki_yarisina_dagitiliyor(self):
        from apps.matches.dizilim import dizilim_verisi

        takimlar = {t["kod"]: t for t in dizilim_verisi(self.mac)}
        a_ortalama = sum(o["x"] for o in takimlar["a"]["oyuncular"]) / len(
            takimlar["a"]["oyuncular"]
        )
        b_ortalama = sum(o["x"] for o in takimlar["b"]["oyuncular"]) / len(
            takimlar["b"]["oyuncular"]
        )
        self.assertLess(a_ortalama, 50)
        self.assertGreater(b_ortalama, 50)

    def test_konumlar_kaydediliyor(self):
        self.client.force_login(self.ozan)
        hedef = self._a_takimi()[1]  # A takımı: sol yarı
        self.client.post(
            reverse("matches:dizilim_duzenle", args=[self.mac.pk]),
            {f"x_{hedef.pk}": "30", f"y_{hedef.pk}": "70"},
        )
        katilim = Katilim.objects.get(mac=self.mac, kullanici=hedef)
        self.assertEqual((katilim.poz_x, katilim.poz_y), (30, 70))

    def test_oyuncu_rakip_yariya_gecemiyor(self):
        """
        A takımı solda, B takımı sağda kalmalı.

        Karışırlarsa dizilim okunamaz hâle geliyordu. Tarayıcı tarafında da
        engelleniyor ama sunucu istemciye güvenmiyor.
        """
        from apps.matches.dizilim import takim_araligi

        self.client.force_login(self.ozan)
        a_oyuncusu = self._a_takimi()[1]
        b_oyuncusu = self._b_takimi()[0]

        self.client.post(
            reverse("matches:dizilim_duzenle", args=[self.mac.pk]),
            {
                # A oyuncusu sağ yarıya, B oyuncusu sol yarıya itilmeye çalışılıyor
                f"x_{a_oyuncusu.pk}": "90", f"y_{a_oyuncusu.pk}": "50",
                f"x_{b_oyuncusu.pk}": "10", f"y_{b_oyuncusu.pk}": "50",
            },
        )

        a_alt, a_ust = takim_araligi("a")
        b_alt, b_ust = takim_araligi("b")

        a_katilim = Katilim.objects.get(mac=self.mac, kullanici=a_oyuncusu)
        b_katilim = Katilim.objects.get(mac=self.mac, kullanici=b_oyuncusu)

        self.assertLessEqual(a_katilim.poz_x, a_ust, "A takımı sağ yarıya geçti")
        self.assertGreaterEqual(b_katilim.poz_x, b_alt, "B takımı sol yarıya geçti")
        # Yarılar çakışmamalı.
        self.assertLess(a_ust, b_alt)

    def test_saha_disi_konumlar_kirpiliyor(self):
        """Bozuk ya da kötü niyetli gönderim dizilimi bozmasın."""
        from apps.matches.dizilim import takim_araligi

        self.client.force_login(self.ozan)
        hedef = self._b_takimi()[0]
        self.client.post(
            reverse("matches:dizilim_duzenle", args=[self.mac.pk]),
            {f"x_{hedef.pk}": "9999", f"y_{hedef.pk}": "-50"},
        )
        katilim = Katilim.objects.get(mac=self.mac, kullanici=hedef)
        _, ust = takim_araligi("b")
        self.assertEqual((katilim.poz_x, katilim.poz_y), (ust, 0))

    def test_istatistikler_kaydediliyor(self):
        self.client.force_login(self.ozan)
        hedef = self.oyuncular[0]
        self.client.post(
            reverse("matches:dizilim_duzenle", args=[self.mac.pk]),
            {
                f"x_{hedef.pk}": "40", f"y_{hedef.pk}": "40",
                f"gol_{hedef.pk}": "2", f"asist_{hedef.pk}": "1",
                f"sari_{hedef.pk}": "1", f"kirmizi_{hedef.pk}": "1",
            },
        )
        katilim = Katilim.objects.get(mac=self.mac, kullanici=hedef)
        self.assertEqual((katilim.gol, katilim.asist), (2, 1))
        self.assertEqual(katilim.sari_kart, 1)
        self.assertTrue(katilim.kirmizi_kart)

    def test_grup_ayari_kapaliyken_istatistik_gosterilmiyor(self):
        """Veri tutulur ama sahada görünmez."""
        from apps.matches.dizilim import dizilim_verisi

        Katilim.objects.filter(mac=self.mac, kullanici=self.oyuncular[0]).update(
            gol=3, asist=2, sari_kart=1, kirmizi_kart=True
        )
        self.assertFalse(self.grup.gol_gosterilsin)

        takimlar = dizilim_verisi(self.mac)
        hepsi = [o for t in takimlar for o in t["oyuncular"]]
        self.assertTrue(all(o["gol"] == 0 for o in hepsi))
        self.assertTrue(all(o["kart"] == "" for o in hepsi))

    def test_grup_ayari_aciksa_istatistik_gosteriliyor(self):
        from apps.matches.dizilim import dizilim_verisi

        Katilim.objects.filter(mac=self.mac, kullanici=self.oyuncular[0]).update(
            gol=3, sari_kart=1
        )
        self.grup.gol_gosterilsin = True
        self.grup.kart_gosterilsin = True
        self.grup.save()

        takimlar = dizilim_verisi(self.mac)
        hepsi = [o for t in takimlar for o in t["oyuncular"]]
        self.assertTrue(any(o["gol"] == 3 for o in hepsi))
        self.assertTrue(any(o["kart"] == "sari" for o in hepsi))

    def test_kart_turleri_ayirt_ediliyor(self):
        """İkinci sarıdan kırmızı, doğrudan kırmızıdan farklı gösterilmeli."""
        from apps.matches.dizilim import kart_turu

        self.grup.kart_gosterilsin = True
        self.grup.save()

        katilim = Katilim.objects.get(mac=self.mac, kullanici=self.oyuncular[0])

        katilim.sari_kart, katilim.kirmizi_kart = 0, False
        self.assertEqual(kart_turu(katilim)[0], "")

        katilim.sari_kart = 1
        self.assertEqual(kart_turu(katilim)[0], "sari")

        katilim.sari_kart, katilim.kirmizi_kart = 0, True
        self.assertEqual(kart_turu(katilim)[0], "kirmizi")

        # İki sarı: doğrudan kırmızıdan ayrı bir görünüm.
        katilim.sari_kart, katilim.kirmizi_kart = 2, False
        self.assertEqual(kart_turu(katilim)[0], "ikinci-sari")

        # İki sarı + kırmızı işaretliyse yine ikinci sarı kazanır.
        katilim.kirmizi_kart = True
        self.assertEqual(kart_turu(katilim)[0], "ikinci-sari")

    def test_gol_toplami_skoru_asamaz(self):
        """3-1 biten maçta A takımı 5 gol atmış olamaz."""
        self.mac.skor_a, self.mac.skor_b = 3, 1
        self.mac.save()
        self.client.force_login(self.ozan)

        a_takimi = self._a_takimi()
        veri = {}
        for k in self.herkes:
            veri[f"x_{k.pk}"] = "20"
            veri[f"y_{k.pk}"] = "50"
        # A takımına toplam 5 gol yazdırmaya çalış
        veri[f"gol_{a_takimi[0].pk}"] = "3"
        veri[f"gol_{a_takimi[1].pk}"] = "2"

        self.client.post(reverse("matches:dizilim_duzenle", args=[self.mac.pk]), veri)

        # Hiçbiri kaydedilmemeli.
        self.assertEqual(
            Katilim.objects.get(mac=self.mac, kullanici=a_takimi[0]).gol, 0
        )

    def test_asist_toplami_skoru_asamaz(self):
        """Her golün en fazla bir asisti olabilir."""
        self.mac.skor_a, self.mac.skor_b = 2, 0
        self.mac.save()
        self.client.force_login(self.ozan)

        a_takimi = self._a_takimi()
        veri = {}
        for k in self.herkes:
            veri[f"x_{k.pk}"] = "20"
            veri[f"y_{k.pk}"] = "50"
        veri[f"asist_{a_takimi[0].pk}"] = "3"

        self.client.post(reverse("matches:dizilim_duzenle", args=[self.mac.pk]), veri)
        self.assertEqual(
            Katilim.objects.get(mac=self.mac, kullanici=a_takimi[0]).asist, 0
        )

    def test_skorla_tutarli_gol_kaydediliyor(self):
        self.mac.skor_a, self.mac.skor_b = 3, 1
        self.mac.save()
        self.client.force_login(self.ozan)

        a_takimi = self._a_takimi()
        veri = {}
        for k in self.herkes:
            veri[f"x_{k.pk}"] = "20"
            veri[f"y_{k.pk}"] = "50"
        veri[f"gol_{a_takimi[0].pk}"] = "2"
        veri[f"gol_{a_takimi[1].pk}"] = "1"
        veri[f"asist_{a_takimi[2].pk}"] = "2"

        self.client.post(reverse("matches:dizilim_duzenle", args=[self.mac.pk]), veri)
        self.assertEqual(
            Katilim.objects.get(mac=self.mac, kullanici=a_takimi[0]).gol, 2
        )

    def test_skor_yokken_gol_denetlenmiyor(self):
        """Üst sınır bilinmiyorsa kısıtlanacak bir şey de yok."""
        self.client.force_login(self.ozan)
        hedef = self._a_takimi()[0]
        veri = {f"x_{hedef.pk}": "20", f"y_{hedef.pk}": "50", f"gol_{hedef.pk}": "4"}

        self.client.post(reverse("matches:dizilim_duzenle", args=[self.mac.pk]), veri)
        self.assertEqual(Katilim.objects.get(mac=self.mac, kullanici=hedef).gol, 4)

    def test_mac_puani_rozette_gosteriliyor(self):
        from apps.matches.dizilim import dizilim_verisi

        hedef = self._a_takimi()[1]
        self._puanla(hedef, [(v, 9) for v in self._b_takimi()[:3]])

        takimlar = dizilim_verisi(self.mac)
        satir = next(
            o for t in takimlar for o in t["oyuncular"] if o["kullanici"].pk == hedef.pk
        )
        self.assertEqual(satir["puan"], 9.0)
        self.assertEqual(satir["puan_sinifi"], "puan-mor")

    def test_karantinadaki_puan_rozete_yansimiyor(self):
        from apps.matches.dizilim import dizilim_verisi

        hedef = self._a_takimi()[1]
        self._puanla(hedef, [(v, 10) for v in self._b_takimi()[:3]])
        Puan.objects.filter(puanlanan=hedef).update(karantinada=True)

        takimlar = dizilim_verisi(self.mac)
        satir = next(
            o for t in takimlar for o in t["oyuncular"] if o["kullanici"].pk == hedef.pk
        )
        self.assertIsNone(satir["puan"])


class UyeIstatistikTesti(TestCase):
    """Grup içi oyuncu istatistik sayfası."""

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.digerleri = [kullanici(f"o{i}@example.com", f"Oyuncu {i}") for i in range(5)]
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        for k in self.digerleri:
            Uyelik.objects.create(
                grup=self.grup, kullanici=k, rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI
            )

    def _mac(self, gun_once: int, skor_a: int | None, skor_b: int | None,
             ozan_takimi="a", ozan_oynadi=True) -> Mac:
        mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=gun_once),
            olusturan=self.ozan,
            skor_a=skor_a,
            skor_b=skor_b,
        )
        if ozan_oynadi:
            Katilim.objects.create(
                mac=mac, kullanici=self.ozan, yanit=Katilim.Yanit.GELIYORUM,
                katildi=True, takim=ozan_takimi,
            )
        for i, k in enumerate(self.digerleri):
            Katilim.objects.create(
                mac=mac, kullanici=k, yanit=Katilim.Yanit.GELIYORUM,
                katildi=True, takim="b" if i % 2 == 0 else "a",
            )
        return mac

    def _ist(self):
        from apps.groups.istatistik import uye_istatistikleri

        return uye_istatistikleri(self.grup, self.ozan)

    def test_sonuc_dizisi_en_yeniden_eskiye(self):
        self._mac(gun_once=20, skor_a=1, skor_b=3)  # M
        self._mac(gun_once=15, skor_a=2, skor_b=2)  # B
        self._mac(gun_once=10, skor_a=4, skor_b=0)  # G
        self._mac(gun_once=5, skor_a=3, skor_b=1)   # G

        dizi = [s.sonuc for s in self._ist()["son_maclar"]]
        self.assertEqual(dizi, ["G", "G", "B", "M"])

    def test_galibiyet_serisi(self):
        self._mac(gun_once=20, skor_a=0, skor_b=1)  # M
        self._mac(gun_once=15, skor_a=2, skor_b=0)  # G
        self._mac(gun_once=10, skor_a=1, skor_b=0)  # G
        self._mac(gun_once=5, skor_a=3, skor_b=0)   # G

        ist = self._ist()
        self.assertEqual(ist["guncel_seri"], 3)
        self.assertEqual(ist["en_uzun_seri"], 3)

    def test_seri_maglubiyetle_kesiliyor(self):
        self._mac(gun_once=20, skor_a=2, skor_b=0)  # G
        self._mac(gun_once=15, skor_a=1, skor_b=0)  # G
        self._mac(gun_once=5, skor_a=0, skor_b=2)   # M (en yeni)

        ist = self._ist()
        self.assertEqual(ist["guncel_seri"], 0)
        self.assertEqual(ist["en_uzun_seri"], 2)

    def test_gbm_dokumu_ve_galibiyet_orani(self):
        self._mac(gun_once=20, skor_a=2, skor_b=0)
        self._mac(gun_once=15, skor_a=0, skor_b=2)
        self._mac(gun_once=10, skor_a=1, skor_b=1)
        self._mac(gun_once=5, skor_a=3, skor_b=1)

        ist = self._ist()
        self.assertEqual((ist["galibiyet"], ist["beraberlik"], ist["maglubiyet"]), (2, 1, 1))
        self.assertEqual(ist["galibiyet_orani"], 50)

    def test_katilim_orani(self):
        self._mac(gun_once=20, skor_a=1, skor_b=0)
        self._mac(gun_once=15, skor_a=1, skor_b=0)
        self._mac(gun_once=10, skor_a=1, skor_b=0, ozan_oynadi=False)
        self._mac(gun_once=5, skor_a=1, skor_b=0, ozan_oynadi=False)

        ist = self._ist()
        self.assertEqual(ist["toplam_mac"], 4)
        self.assertEqual(ist["oynanan_mac"], 2)
        self.assertEqual(ist["katilim_orani"], 50)

    def test_iptal_edilen_mac_hicbir_sayiya_girmiyor(self):
        self._mac(gun_once=10, skor_a=3, skor_b=0)
        iptal = self._mac(gun_once=5, skor_a=9, skor_b=0)
        iptal.iptal = True
        iptal.save()

        ist = self._ist()
        self.assertEqual(ist["toplam_mac"], 1)
        self.assertEqual(ist["galibiyet"], 1)

    def test_skoru_girilmemis_mac_seriye_girmiyor(self):
        self._mac(gun_once=10, skor_a=2, skor_b=0)
        self._mac(gun_once=5, skor_a=None, skor_b=None)

        ist = self._ist()
        self.assertEqual(ist["sonuclu_mac"], 1)
        # Ama oynanan maç sayısına dâhil.
        self.assertEqual(ist["oynanan_mac"], 2)

    def test_gol_asist_grup_ayarina_bagli(self):
        mac = self._mac(gun_once=5, skor_a=2, skor_b=0)
        Katilim.objects.filter(mac=mac, kullanici=self.ozan).update(
            gol=2, asist=1, sari_kart=1
        )

        kapali = self._ist()
        self.assertIsNone(kapali["gol"])
        self.assertIsNone(kapali["asist"])
        self.assertIsNone(kapali["sari_kart"])

        self.grup.gol_gosterilsin = True
        self.grup.asist_gosterilsin = True
        self.grup.kart_gosterilsin = True
        self.grup.save()

        acik = self._ist()
        self.assertEqual(acik["gol"], 2)
        self.assertEqual(acik["asist"], 1)
        self.assertEqual(acik["sari_kart"], 1)

    def test_macin_adami_sayisi(self):
        mac = self._mac(gun_once=5, skor_a=3, skor_b=0)
        for veren in self.digerleri[:3]:
            Puan.objects.create(mac=mac, puanlayan=veren, puanlanan=self.ozan, deger=9)

        self.assertEqual(self._ist()["macin_adami"], 1)

    def test_sayfa_uyeye_acik_yabanciya_kapali(self):
        self._mac(gun_once=5, skor_a=1, skor_b=0)
        adres = reverse("groups:uye_istatistik", args=[self.grup.genel_id, self.ozan.pk])

        self.client.force_login(self.digerleri[0])
        self.assertEqual(self.client.get(adres).status_code, 200)

        yabanci = kullanici("yabanci@example.com", "Yabancı")
        self.client.force_login(yabanci)
        self.assertEqual(self.client.get(adres).status_code, 403)

    def test_grup_disindaki_kullanici_icin_404(self):
        yabanci = kullanici("yabanci@example.com", "Yabancı")
        self.client.force_login(self.ozan)
        yanit = self.client.get(
            reverse("groups:uye_istatistik", args=[self.grup.genel_id, yabanci.pk])
        )
        self.assertEqual(yanit.status_code, 404)


class TopluMacinAdamiTesti(_TakimliMacKurulumu):
    """Toplu sayaç, tek maçlık hesapla aynı sonucu vermeli."""

    def test_toplu_sayac_tek_tek_hesapla_ayni(self):
        from apps.ratings.denetim import grup_macin_adami_sayilari, macin_adami

        self.mac.skor_a, self.mac.skor_b = 4, 1
        self.mac.save()
        yildiz = self._a_takimi()[1]
        self._puanla(yildiz, [(v, 9) for v in self._b_takimi()[:3]])
        self._puanla(self._a_takimi()[2], [(v, 6) for v in self._b_takimi()[:3]])

        ikinci = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=5),
            olusturan=self.ozan,
            skor_a=0, skor_b=2,
        )
        for i, k in enumerate(self.herkes):
            Katilim.objects.create(
                mac=ikinci, kullanici=k, yanit=Katilim.Yanit.GELIYORUM,
                katildi=True, takim="a" if i % 2 == 0 else "b",
            )
        b_yildizi = self._b_takimi()[0]
        for veren in self._a_takimi()[:3]:
            Puan.objects.create(
                mac=ikinci, puanlayan=veren, puanlanan=b_yildizi, deger=8
            )

        toplu = grup_macin_adami_sayilari(self.grup)

        tek_tek: dict[int, int] = {}
        for mac in Mac.objects.filter(grup=self.grup):
            for adam in macin_adami(mac):
                tek_tek[adam["kullanici"].pk] = tek_tek.get(adam["kullanici"].pk, 0) + 1

        self.assertEqual(toplu, tek_tek)
        self.assertEqual(toplu.get(yildiz.pk), 1)
        self.assertEqual(toplu.get(b_yildizi.pk), 1)

    def test_skoru_olmayan_mac_sayilmiyor(self):
        from apps.ratings.denetim import grup_macin_adami_sayilari

        self._puanla(self._a_takimi()[1], [(v, 9) for v in self._b_takimi()[:3]])
        self.assertEqual(grup_macin_adami_sayilari(self.grup), {})


class PuanGorunurluguTesti(_TakimliMacKurulumu):
    """
    Puanları görmek için maçta oynayan herkesi puanlamış olmak gerekiyor.

    Amaç: kimse kendi oyunu vermeden başkalarının ortalamasına bakıp ona
    göre oy veremesin, ya da hiç oy vermeden sonucu izlemesin.
    """

    def _hepsini_puanla(self, veren, deger=6):
        for hedef in self.herkes:
            if hedef.pk == veren.pk:
                continue
            Puan.objects.update_or_create(
                mac=self.mac,
                puanlayan=veren,
                puanlanan=hedef,
                defaults={"deger": deger},
            )

    def test_hic_puanlamayan_goremiyor(self):
        from apps.ratings.gorunurluk import puan_gorunurlugu

        durum = puan_gorunurlugu(self.mac, self.oyuncular[0])
        self.assertFalse(durum.gorebilir)
        self.assertEqual(durum.eksik_sayisi, len(self.herkes) - 1)

    def test_eksik_puanlayan_goremiyor(self):
        """Bir kişiyi bile atlamak yeterli."""
        from apps.ratings.gorunurluk import puan_gorunurlugu

        veren = self.oyuncular[0]
        hedefler = [k for k in self.herkes if k.pk != veren.pk]
        for hedef in hedefler[:-1]:  # sonuncusu hariç hepsi
            Puan.objects.create(mac=self.mac, puanlayan=veren, puanlanan=hedef, deger=6)

        durum = puan_gorunurlugu(self.mac, veren)
        self.assertFalse(durum.gorebilir)
        self.assertEqual(durum.eksik_sayisi, 1)

    def test_herkesi_puanlayan_gorebiliyor(self):
        from apps.ratings.gorunurluk import puan_gorunurlugu

        veren = self.oyuncular[0]
        self._hepsini_puanla(veren)
        self.assertTrue(puan_gorunurlugu(self.mac, veren).gorebilir)

    def test_sonradan_eklenen_oyuncu_gorunurlugu_kapatiyor(self):
        """Kadroya biri eklenirse ona da puan verilmeden puanlar gizlenir."""
        from apps.ratings.gorunurluk import puan_gorunurlugu

        veren = self.oyuncular[0]
        self._hepsini_puanla(veren)
        self.assertTrue(puan_gorunurlugu(self.mac, veren).gorebilir)

        yeni = kullanici("yeni@example.com", "Yeni Oyuncu")
        Uyelik.objects.create(
            grup=self.grup, kullanici=yeni, rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI
        )
        Katilim.objects.create(
            mac=self.mac, kullanici=yeni, yanit=Katilim.Yanit.GELIYORUM,
            katildi=True, takim="a",
        )

        durum = puan_gorunurlugu(self.mac, veren)
        self.assertFalse(durum.gorebilir)
        self.assertEqual(durum.eksik_sayisi, 1)

    def test_sure_dolunca_herkes_gorebiliyor(self):
        from apps.ratings.gorunurluk import puan_gorunurlugu

        self.mac.baslangic = timezone.now() - timezone.timedelta(
            days=settings.RATING_WINDOW_DAYS + 1
        )
        self.mac.save()

        durum = puan_gorunurlugu(self.mac, self.oyuncular[0])
        self.assertTrue(durum.gorebilir)
        self.assertTrue(durum.sure_doldu)

    def test_yoneticiler_muaf(self):
        from apps.ratings.gorunurluk import puan_gorunurlugu

        # Ozan grup yöneticisi, hiç puan vermedi
        self.assertTrue(puan_gorunurlugu(self.mac, self.ozan).gorebilir)

        nihai = kullanici("dev@example.com", "Nihai Yönetici")
        nihai.is_superuser = True
        nihai.save()
        self.assertTrue(puan_gorunurlugu(self.mac, nihai).gorebilir)

    def test_puanlar_sayfa_kaynaginda_da_yok(self):
        """
        Gizleme şablonda değil görünümde yapılıyor; puan HTML'e hiç girmemeli.

        Aksi hâlde "ekranda görünmüyor ama kaynağa bakınca var" olurdu.
        """
        hedef = self._a_takimi()[1]
        for veren in self._b_takimi()[:3]:
            Puan.objects.create(mac=self.mac, puanlayan=veren, puanlanan=hedef, deger=9)

        izleyen = self.oyuncular[0]  # yönetici değil, hiç puanlamadı
        self.client.force_login(izleyen)
        govde = self.client.get(
            reverse("matches:dizilim", args=[self.mac.pk])
        ).content.decode("utf-8")

        self.assertIn("tüm oyunculara puan verilmeli", govde)
        self.assertNotIn("puan-rozeti puan-", govde)
        self.assertNotIn("Maçın adamı", govde)

    def test_puanlayan_dizilimde_puanlari_goruyor(self):
        hedef = self._a_takimi()[1]
        for veren in self._b_takimi()[:3]:
            Puan.objects.create(mac=self.mac, puanlayan=veren, puanlanan=hedef, deger=9)

        izleyen = self.oyuncular[0]
        self._hepsini_puanla(izleyen)

        self.client.force_login(izleyen)
        govde = self.client.get(
            reverse("matches:dizilim", args=[self.mac.pk])
        ).content.decode("utf-8")
        self.assertNotIn("tüm oyunculara puan verilmeli", govde)
        self.assertIn("puan-rozeti puan-", govde)

    def test_sonuclar_tek_oyla_acilmiyor(self):
        """Eskiden tek bir oy sonuçları açıyordu; artık hepsi gerekli."""
        veren = self.oyuncular[0]
        Puan.objects.create(
            mac=self.mac, puanlayan=veren, puanlanan=self.oyuncular[1], deger=7
        )
        self.client.force_login(veren)
        govde = self.client.get(
            reverse("ratings:sonuclar", args=[self.mac.pk])
        ).content.decode("utf-8")
        self.assertIn("tüm oyunculara puan verilmeli", govde)


class ToplamlaraSizmaTesti(_TakimliMacKurulumu):
    """
    Maç sayfasını gizlemek tek başına yetmiyor.

    Grup sıralaması, üye istatistikleri ve form ortalaması aynı puanlardan
    besleniyor; sayfayı maçtan önce ve sonra açan biri farktan puanı
    çıkarabilirdi. Puanlamasını tamamlamayan kişiye o maç hiçbir toplamda
    görünmemeli.
    """

    def setUp(self):
        super().setUp()
        self.mac.skor_a, self.mac.skor_b = 3, 1
        self.mac.save()
        self.hedef = self._a_takimi()[1]
        for veren in self._b_takimi()[:4]:
            Puan.objects.create(
                mac=self.mac, puanlayan=veren, puanlanan=self.hedef, deger=9
            )

    def _hepsini_puanla(self, veren, deger=6):
        for hedef in self.herkes:
            if hedef.pk != veren.pk:
                Puan.objects.update_or_create(
                    mac=self.mac,
                    puanlayan=veren,
                    puanlanan=hedef,
                    defaults={"deger": deger},
                )

    def _ist(self, izleyen):
        from apps.groups.istatistik import uye_istatistikleri

        return uye_istatistikleri(self.grup, self.hedef, izleyen=izleyen)

    def test_puanlamayan_istatistikte_puan_gormuyor(self):
        ist = self._ist(self.oyuncular[1])
        self.assertIsNone(ist["ortalama"])
        self.assertIsNone(ist["form_ortalamasi"])
        self.assertEqual(ist["macin_adami"], 0)
        self.assertEqual(ist["gizli_mac_sayisi"], 1)
        # Puanla ilgisi olmayan sayılar etkilenmiyor.
        self.assertEqual(ist["oynanan_mac"], 1)

    def test_puanlamayi_tamamlayan_goruyor(self):
        izleyen = self.oyuncular[1]
        self._hepsini_puanla(izleyen)

        ist = self._ist(izleyen)
        self.assertIsNotNone(ist["ortalama"])
        self.assertIsNotNone(ist["form_ortalamasi"])
        self.assertEqual(ist["macin_adami"], 1)
        self.assertEqual(ist["gizli_mac_sayisi"], 0)

    def test_sure_dolunca_puanlamayana_da_aciliyor(self):
        self.mac.baslangic = timezone.now() - timezone.timedelta(
            days=settings.RATING_WINDOW_DAYS + 1
        )
        self.mac.save()

        ist = self._ist(self.oyuncular[1])
        self.assertIsNotNone(ist["ortalama"])
        self.assertEqual(ist["gizli_mac_sayisi"], 0)

    def test_yonetici_muaf(self):
        ist = self._ist(self.ozan)
        self.assertIsNotNone(ist["ortalama"])
        self.assertEqual(ist["gizli_mac_sayisi"], 0)

    def test_grup_siralamasinda_da_gizli(self):
        from apps.ratings.hesaplar import grup_siralamasi

        izleyen = self.oyuncular[1]
        self.assertEqual(grup_siralamasi(self.grup, izleyen=izleyen), [])

        self._hepsini_puanla(izleyen)
        adlar = [s["kullanici"].pk for s in grup_siralamasi(self.grup, izleyen=izleyen)]
        self.assertIn(self.hedef.pk, adlar)

    def test_siralama_sayfasi_puanlamayana_kapali(self):
        self.client.force_login(self.oyuncular[1])
        govde = self.client.get(
            reverse("ratings:siralama", args=[self.grup.genel_id])
        ).content.decode("utf-8")

        self.assertIn("tüm oyunculara puan verilmeli", govde)
        self.assertIn("Sıralama için yeterli puan yok", govde)

    def test_mac_detayinda_macin_adami_gizli(self):
        izleyen = self.oyuncular[1]
        self.client.force_login(izleyen)
        adres = reverse("matches:detay", args=[self.mac.pk])

        govde = self.client.get(adres).content.decode("utf-8")
        self.assertNotIn("Maçın adamı</span>", govde)
        self.assertIn("puanlamanı tamamlayınca görünür", govde)

        self._hepsini_puanla(izleyen)
        govde = self.client.get(adres).content.decode("utf-8")
        self.assertIn("Maçın adamı", govde)


class TakimPuanOzetiTesti(_TakimliMacKurulumu):
    """Dizilimde takım başına ortalama ve toplam."""

    def test_ortalama_ve_toplam_hesaplaniyor(self):
        from apps.matches.dizilim import dizilim_verisi

        a = self._a_takimi()
        # İki oyuncuya sırasıyla 8 ve 6 ortalama
        for veren in self._b_takimi()[:2]:
            Puan.objects.create(mac=self.mac, puanlayan=veren, puanlanan=a[0], deger=8)
            Puan.objects.create(mac=self.mac, puanlayan=veren, puanlanan=a[1], deger=6)

        takim = next(t for t in dizilim_verisi(self.mac) if t["kod"] == "a")
        self.assertEqual(takim["toplam_puan"], 14.0)
        self.assertEqual(takim["ortalama_puan"], 7.0)
        self.assertEqual(takim["puanli_oyuncu"], 2)

    def test_puansiz_oyuncu_ortalamayi_dusurmuyor(self):
        from apps.matches.dizilim import dizilim_verisi

        a = self._a_takimi()
        for veren in self._b_takimi()[:2]:
            Puan.objects.create(mac=self.mac, puanlayan=veren, puanlanan=a[0], deger=8)

        takim = next(t for t in dizilim_verisi(self.mac) if t["kod"] == "a")
        self.assertEqual(takim["ortalama_puan"], 8.0)
        self.assertEqual(takim["puanli_oyuncu"], 1)

    def test_gizlenince_ozet_de_gidiyor(self):
        from apps.matches.dizilim import dizilim_verisi, puanlari_gizle

        a = self._a_takimi()
        for veren in self._b_takimi()[:2]:
            Puan.objects.create(mac=self.mac, puanlayan=veren, puanlanan=a[0], deger=8)

        takimlar = puanlari_gizle(dizilim_verisi(self.mac))
        for takim in takimlar:
            self.assertIsNone(takim["ortalama_puan"])
            self.assertIsNone(takim["toplam_puan"])
            for oyuncu in takim["oyuncular"]:
                self.assertIsNone(oyuncu["puan"])
                self.assertFalse(oyuncu["macin_adami"])


class PuanDegistirmeHakkiTesti(_TakimliMacKurulumu):
    """Her oyuncuya en fazla iki kez puan yazılabilir (ilk oy + bir düzeltme)."""

    def _gonder(self, veren, degerler: dict):
        self.client.force_login(veren)
        return self.client.post(
            reverse("ratings:puanla", args=[self.mac.pk]),
            {f"puan_{k.pk}": str(v) for k, v in degerler.items()},
        )

    def test_ilk_oy_ve_bir_duzeltme_gecerli(self):
        veren = self.oyuncular[0]
        hedef = self.oyuncular[1]

        self._gonder(veren, {hedef: 5})
        kayit = Puan.objects.get(mac=self.mac, puanlayan=veren, puanlanan=hedef)
        self.assertEqual((kayit.deger, kayit.yazim_sayisi), (5, 1))

        self._gonder(veren, {hedef: 8})
        kayit.refresh_from_db()
        self.assertEqual((kayit.deger, kayit.yazim_sayisi), (8, 2))

    def test_ucuncu_yazim_reddediliyor(self):
        veren = self.oyuncular[0]
        hedef = self.oyuncular[1]

        self._gonder(veren, {hedef: 5})
        self._gonder(veren, {hedef: 8})
        self._gonder(veren, {hedef: 10})

        kayit = Puan.objects.get(mac=self.mac, puanlayan=veren, puanlanan=hedef)
        self.assertEqual(kayit.deger, 8, "üçüncü değişiklik uygulanmamalı")
        self.assertEqual(kayit.yazim_sayisi, 2)

    def test_ayni_degeri_kaydetmek_hak_yakmiyor(self):
        """
        Form herkesi birden gönderiyor; tek bir oyuncuyu düzelten kişi
        diğerlerinin hakkını harcamamalı.
        """
        veren = self.oyuncular[0]
        hedef = self.oyuncular[1]

        self._gonder(veren, {hedef: 5})
        self._gonder(veren, {hedef: 5})
        self._gonder(veren, {hedef: 5})

        kayit = Puan.objects.get(mac=self.mac, puanlayan=veren, puanlanan=hedef)
        self.assertEqual(kayit.yazim_sayisi, 1, "aynı değer hak yakmamalı")

        # Hak hâlâ duruyor: gerçek bir değişiklik yapılabilmeli.
        self._gonder(veren, {hedef: 9})
        kayit.refresh_from_db()
        self.assertEqual((kayit.deger, kayit.yazim_sayisi), (9, 2))

    def test_hak_oyuncu_bazinda_tutuluyor(self):
        """Bir oyuncunun hakkının dolması diğerlerini etkilememeli."""
        veren = self.oyuncular[0]
        biri, digeri = self.oyuncular[1], self.oyuncular[2]

        self._gonder(veren, {biri: 4, digeri: 4})
        self._gonder(veren, {biri: 6, digeri: 4})  # yalnızca "biri" değişti
        self._gonder(veren, {biri: 9, digeri: 7})  # biri kilitli, digeri serbest

        biri_kayit = Puan.objects.get(mac=self.mac, puanlayan=veren, puanlanan=biri)
        digeri_kayit = Puan.objects.get(mac=self.mac, puanlayan=veren, puanlanan=digeri)
        self.assertEqual(biri_kayit.deger, 6, "hakkı dolan oyuncu değişmemeli")
        self.assertEqual(digeri_kayit.deger, 7, "hakkı olan oyuncu değişmeli")

    def test_kalan_hak_formda_gosteriliyor(self):
        from apps.ratings.gorunurluk import kalan_yazim_haklari

        veren = self.oyuncular[0]
        hedef = self.oyuncular[1]
        self._gonder(veren, {hedef: 5})

        haklar = kalan_yazim_haklari(self.mac, veren)
        self.assertEqual(haklar[hedef.pk], settings.RATING_MAX_WRITES - 1)
        # Hiç puanlanmamış birinde hak tam.
        self.assertEqual(haklar[self.oyuncular[2].pk], settings.RATING_MAX_WRITES)


class AramaMotoruTesti(TestCase):
    """Google'ın arama sonucunda simge gösterebilmesi için gerekenler."""

    def test_favicon_kokten_kararli_adreste(self):
        yanit = self.client.get("/favicon.ico")
        self.assertEqual(yanit.status_code, 200)
        self.assertEqual(yanit["Content-Type"], "image/x-icon")
        # Karma içeren adres her değişiklikte kayıyor; Google kararlı adres istiyor.
        self.assertNotIn("static", yanit.request["PATH_INFO"])

    def test_logo_erisilebilir(self):
        yanit = self.client.get("/logo.png")
        self.assertEqual(yanit.status_code, 200)
        self.assertEqual(yanit["Content-Type"], "image/png")

    def test_robots_simgeleri_engellemiyor(self):
        govde = self.client.get("/robots.txt").content.decode("utf-8")
        self.assertIn("Allow: /favicon.ico", govde)
        self.assertIn("Allow: /logo.png", govde)
        # Kişisel veri taramaya kapalı olmalı.
        for gizli in ["/gruplar/", "/maclar/", "/sohbet/", "/dosya/"]:
            self.assertIn(f"Disallow: {gizli}", govde)

    def test_sitemap_yalnizca_herkese_acik_sayfalar(self):
        """
        Site haritasında yalnızca giriş gerektirmeyen sayfalar olmalı.

        Sayı sabitlenmiyor; her adresin gerçekten giriş istemediği
        doğrulanıyor. Yanlışlıkla korumalı bir sayfa eklenirse yakalanır.
        """
        import re

        govde = self.client.get("/sitemap.xml").content.decode("utf-8")
        self.assertIn("<urlset", govde)

        yollar = re.findall(r"<loc>https?://[^/]+(/[^<]*)</loc>", govde)
        self.assertIn("/gizlilik/", yollar)
        self.assertIn("/kurallar/", yollar)
        self.assertIn("/hesap-silme/", yollar)

        for yol in yollar:
            with self.subTest(yol=yol):
                self.assertEqual(
                    self.client.get(yol).status_code,
                    200,
                    f"{yol} giriş gerektiriyor, site haritasında olmamalı",
                )

    def test_sayfada_yapilandirilmis_veri_var(self):
        govde = self.client.get(reverse("core:home")).content.decode("utf-8")
        self.assertIn("application/ld+json", govde)
        self.assertIn('"@type": "Organization"', govde)
        self.assertIn("/logo.png", govde)
        self.assertIn('href="/favicon.ico"', govde)


class GelistiriciRozetiTesti(TestCase):
    def test_nihai_yonetici_rozeti_gorunuyor(self):
        gelistirici = kullanici("dev@example.com", "Ozan Kaya")
        gelistirici.is_superuser = True
        gelistirici.is_staff = True
        gelistirici.save()

        grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=gelistirici)
        Uyelik.objects.create(
            grup=grup, kullanici=gelistirici,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )

        self.client.force_login(gelistirici)
        govde = self.client.get(
            reverse("groups:uyeler", args=[grup.genel_id])
        ).content.decode("utf-8")
        self.assertIn("Geliştirici", govde)

    def test_sradan_uyede_rozet_yok(self):
        ozan = kullanici("ozan@example.com", "Ozan Kaya")
        grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=ozan)
        Uyelik.objects.create(
            grup=grup, kullanici=ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        self.client.force_login(ozan)
        govde = self.client.get(
            reverse("groups:uyeler", args=[grup.genel_id])
        ).content.decode("utf-8")
        self.assertNotIn("Geliştirici", govde)


class AnaEkranUygulamasiTesti(TestCase):
    """Ana ekrana eklenebilir uygulama (PWA) gereksinimleri."""

    def test_manifest_dogru_icerik_turuyle_sunuluyor(self):
        yanit = self.client.get(reverse("core:manifest"))
        self.assertEqual(yanit.status_code, 200)
        # Statik dosya olarak sunulsaydı nginx bunu octet-stream yapardı ve
        # tarayıcı manifesti yok sayardı.
        self.assertEqual(yanit["Content-Type"], "application/manifest+json")

    def test_manifest_icerigi(self):
        import json

        veri = json.loads(self.client.get(reverse("core:manifest")).content)
        self.assertEqual(veri["name"], "Halısaha Defteri")
        self.assertEqual(veri["short_name"], "Halısaha Defteri")
        # Uygulama panele açılmalı, tanıtım sayfasına değil.
        self.assertEqual(veri["start_url"], "/panel/")
        self.assertEqual(veri["display"], "standalone")

        boyutlar = {i["sizes"] for i in veri["icons"]}
        self.assertIn("192x192", boyutlar)
        self.assertIn("512x512", boyutlar)
        # Android ikonu kırpıyor; maskable sürüm olmazsa saha çizgileri kesilir.
        self.assertIn("maskable", {i["purpose"] for i in veri["icons"]})

    def test_servis_calisani_kokten_sunuluyor(self):
        """Yetki alanı bulunduğu klasörle sınırlı; kökte olmak zorunda."""
        self.assertEqual(reverse("core:servis_calisani"), "/sw.js")

        yanit = self.client.get("/sw.js")
        self.assertEqual(yanit.status_code, 200)
        self.assertIn("javascript", yanit["Content-Type"])
        self.assertEqual(yanit["Service-Worker-Allowed"], "/")
        # Önbelleğe alınırsa yayınlanan düzeltmeler cihazlara ulaşmıyor.
        self.assertIn("no-cache", yanit["Cache-Control"])

    def test_servis_calisani_ozel_veriyi_onbellege_almiyor(self):
        """
        Telefon paylaşılabilir: kullanıcıya ait hiçbir şey cihazda kalmamalı.

        Yalnızca /static/ altı saklanıyor; fotoğraflar ve sayfalar değil.
        """
        govde = self.client.get("/sw.js").content.decode("utf-8")
        self.assertIn("statikMi", govde)
        self.assertNotIn('"/dosya/', govde)
        self.assertNotIn('"/sohbet/', govde)

    def test_cevrimdisi_sayfasi_kisisel_veri_icermiyor(self):
        yanit = self.client.get(reverse("core:cevrimdisi"))
        self.assertEqual(yanit.status_code, 200)
        # Giriş yapılmamışken bile açılmalı: servis çalışanı bunu saklıyor.
        self.assertContains(yanit, "İnternet bağlantısı yok")

    def test_sayfalarda_manifest_ve_ikon_bagli(self):
        govde = self.client.get(reverse("core:home")).content.decode("utf-8")
        self.assertIn('rel="manifest"', govde)
        self.assertIn("apple-touch-icon", govde)
        self.assertIn('name="theme-color"', govde)
        self.assertIn('content="Halısaha Defteri"', govde)

    def test_ikon_dosyalari_diskte_var(self):
        kok = settings.BASE_DIR / "static" / "img"
        for ad in [
            "ikon-192.png", "ikon-512.png",
            "ikon-maskable-192.png", "ikon-maskable-512.png",
            "apple-touch-icon.png",
        ]:
            with self.subTest(ikon=ad):
                self.assertTrue((kok / ad).is_file(), f"{ad} yok")


class FotografIndirmeTesti(TestCase):
    """Maç fotoğraflarının telefona indirilebilmesi."""

    def setUp(self):
        from apps.core.images import MAC_FOTOGRAFI, gorseli_isle
        from apps.matches.models import MacFotografi

        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.yabanci = kullanici("yabanci@example.com", "Yabancı Kişi")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        Uyelik.objects.create(
            grup=self.grup, kullanici=self.ozan,
            rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI,
        )
        self.mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            olusturan=self.ozan,
        )

        self.gecici = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.gecici, True)
        with override_settings(MEDIA_ROOT=self.gecici):
            icerik, _ = gorseli_isle(
                SimpleUploadedFile("a.jpg", gorsel_uret().read(), content_type="image/jpeg"),
                MAC_FOTOGRAFI,
            )
            self.foto = MacFotografi(mac=self.mac, yukleyen=self.ozan)
            self.foto.dosya.save(icerik.name, icerik, save=True)

    def _oku(self, yanit):
        """Windows'ta dosya kolu açık kalmasın."""
        if hasattr(yanit, "streaming_content"):
            b"".join(yanit.streaming_content)
        yanit.close()
        return yanit

    def test_indir_parametresi_attachment_donduruyor(self):
        self.client.force_login(self.ozan)
        with override_settings(MEDIA_ROOT=self.gecici):
            yanit = self._oku(self.client.get(self.foto.url + "?indir=1"))
        self.assertEqual(yanit.status_code, 200)
        self.assertTrue(yanit["Content-Disposition"].startswith("attachment;"))

    def test_parametresiz_istek_hala_sayfada_gosteriliyor(self):
        """Galeride fotoğrafın inline görünmesi bozulmamalı."""
        self.client.force_login(self.ozan)
        with override_settings(MEDIA_ROOT=self.gecici):
            yanit = self._oku(self.client.get(self.foto.url))
        self.assertTrue(yanit["Content-Disposition"].startswith("inline;"))

    def test_indirilen_dosya_adi_mac_tarihini_tasiyor(self):
        self.client.force_login(self.ozan)
        with override_settings(MEDIA_ROOT=self.gecici):
            yanit = self._oku(self.client.get(self.foto.url + "?indir=1"))
        ad = yanit["Content-Disposition"]
        self.assertIn(timezone.localtime(self.mac.baslangic).strftime("%Y-%m-%d"), ad)
        self.assertIn(".webp", ad)
        # Başlıkta ASCII dışı karakter olmamalı; bazı tarayıcılar adı bozuyor.
        ad.encode("ascii")

    def test_indirme_yetki_kontrolunu_atlatamiyor(self):
        """?indir=1 grup dışındakine kapı açmamalı."""
        self.client.force_login(self.yabanci)
        with override_settings(MEDIA_ROOT=self.gecici):
            yanit = self.client.get(self.foto.url + "?indir=1")
        self.assertEqual(yanit.status_code, 404)

    def test_giris_yapmamis_indiremiyor(self):
        with override_settings(MEDIA_ROOT=self.gecici):
            yanit = self.client.get(self.foto.url + "?indir=1")
        self.assertIn(yanit.status_code, (302, 404))

    def test_galeride_indirme_adresi_var(self):
        self.client.force_login(self.ozan)
        with override_settings(MEDIA_ROOT=self.gecici):
            govde = self.client.get(
                reverse("matches:detay", args=[self.mac.pk])
            ).content.decode("utf-8")
        self.assertIn(f'data-buyutec-indir="{self.foto.url}?indir=1"', govde)


class FotografBuyutecTesti(TestCase):
    """Profil fotoğrafına tıklayınca büyüyen katman."""

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.client.force_login(self.ozan)

    def test_katman_her_sayfada_hazir(self):
        govde = self.client.get(reverse("core:dashboard")).content.decode("utf-8")
        self.assertIn('id="buyutec"', govde)
        self.assertIn("data-buyutec-gorsel", govde)

    def test_fotografsiz_profilde_buyutec_dugmesi_yok(self):
        govde = self.client.get(
            reverse("accounts:profil", args=[self.ozan.pk])
        ).content.decode("utf-8")
        self.assertNotIn("data-buyutec=", govde)

    def test_fotografli_profilde_buyutec_dugmesi_var(self):
        from PIL import Image

        from apps.accounts.models import Profil

        ham = io.BytesIO()
        Image.new("RGB", (70, 70), (10, 120, 60)).save(ham, format="JPEG")

        with tempfile.TemporaryDirectory() as gecici:
            with override_settings(MEDIA_ROOT=gecici):
                self.client.post(
                    reverse("accounts:profil_duzenle"),
                    {
                        "ad_soyad": "Ozan Kaya",
                        "avatar": SimpleUploadedFile(
                            "foto.jpg", ham.getvalue(), content_type="image/jpeg"
                        ),
                    },
                )
                govde = self.client.get(
                    reverse("accounts:profil", args=[self.ozan.pk])
                ).content.decode("utf-8")

                profil = Profil.objects.get(kullanici=self.ozan)
                self.assertIn(f'data-buyutec="{profil.avatar_url}"', govde)


class AvatarDegistirmeTesti(TestCase):
    """
    Yeni profil fotoğrafı yüklenince adresin de değişmesi gerekiyor.

    Adres /dosya/avatar/<avatar_id>/ ve yanıt bir saat önbelleğe alınıyor.
    avatar_id sabit kalırsa dosya diskte değişse bile tarayıcı eski
    fotoğrafı göstermeye devam ediyor: kullanıcıya "güncellendi" yazıyor,
    ekranda hiçbir şey değişmiyor.
    """

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.client.force_login(self.ozan)

    def _yukle(self, renk):
        from PIL import Image

        ham = io.BytesIO()
        Image.new("RGB", (70, 70), renk).save(ham, format="JPEG")
        return SimpleUploadedFile("foto.jpg", ham.getvalue(), content_type="image/jpeg")

    def test_yeni_fotograf_adresi_degistiriyor(self):
        from apps.accounts.models import Profil

        with tempfile.TemporaryDirectory() as gecici:
            with override_settings(MEDIA_ROOT=gecici):
                self.client.post(
                    reverse("accounts:profil_duzenle"),
                    {"ad_soyad": "Ozan Kaya", "avatar": self._yukle((10, 120, 60))},
                )
                profil = Profil.objects.get(kullanici=self.ozan)
                ilk_id = profil.avatar_id
                ilk_url = profil.avatar_url

                self.client.post(
                    reverse("accounts:profil_duzenle"),
                    {"ad_soyad": "Ozan Kaya", "avatar": self._yukle((200, 30, 30))},
                )
                profil.refresh_from_db()

                self.assertNotEqual(
                    profil.avatar_id, ilk_id,
                    "avatar_id aynı kaldı; tarayıcı eski fotoğrafı gösterir",
                )
                self.assertNotEqual(profil.avatar_url, ilk_url)

    def _durum(self, url) -> int:
        """
        İsteği yapar ve yanıtı KAPATIR.

        FileResponse dosyayı açık tutuyor; Windows açık bir dosyanın
        silinmesine izin vermediği için, kapatmadan yeni fotoğraf
        yüklenemiyor. Gerçek sunucuda bunu WSGI katmanı hallediyor.
        """
        yanit = self.client.get(url)
        if hasattr(yanit, "streaming_content"):
            b"".join(yanit.streaming_content)
        yanit.close()
        return yanit.status_code

    def test_eski_adres_artik_bulunamiyor(self):
        """Eski adres 404 dönmeli; önbellekteki kopya böylece geçersizleşir."""
        from apps.accounts.models import Profil

        with tempfile.TemporaryDirectory() as gecici:
            with override_settings(MEDIA_ROOT=gecici):
                self.client.post(
                    reverse("accounts:profil_duzenle"),
                    {"ad_soyad": "Ozan Kaya", "avatar": self._yukle((10, 120, 60))},
                )
                eski_url = Profil.objects.get(kullanici=self.ozan).avatar_url
                self.assertEqual(self._durum(eski_url), 200)

                self.client.post(
                    reverse("accounts:profil_duzenle"),
                    {"ad_soyad": "Ozan Kaya", "avatar": self._yukle((200, 30, 30))},
                )
                self.assertEqual(self._durum(eski_url), 404)

                yeni_url = Profil.objects.get(kullanici=self.ozan).avatar_url
                self.assertEqual(self._durum(yeni_url), 200)


class VekilArkasindaIstemciIPTesti(TestCase):
    """
    Ters vekil arkasında istemci IP'sinin bulunabildiğini doğrular.

    Üretimde gunicorn ile nginx arasında Unix soketi var; soketin karşı
    ucunda IP olmadığı için REMOTE_ADDR boş geliyor. allauth hız sınırlaması
    için IP'yi bulamayınca PermissionDenied fırlatıyor ve **giriş sayfası
    403 veriyor**. Yerelde runserver TCP kullandığı için bu hiç görünmüyordu;
    yalnızca yayında ortaya çıktı. O yüzden testi yazıyoruz.
    """

    def setUp(self):
        from apps.accounts.adapters import AccountAdapter

        self.adaptor = AccountAdapter()
        self.fabrika = RequestFactory()

    def _istek(self, **meta):
        istek = self.fabrika.post("/hesap/login/")
        istek.META.pop("REMOTE_ADDR", None)  # Unix soketi: boş
        istek.META.update(meta)
        return istek

    @override_settings(BEHIND_PROXY=True)
    def test_unix_soketinde_xff_kullanilir(self):
        ip = self.adaptor.get_client_ip(self._istek(HTTP_X_FORWARDED_FOR="203.0.113.9"))
        self.assertEqual(ip, "203.0.113.9")

    @override_settings(BEHIND_PROXY=True)
    def test_xff_yoksa_x_real_ip_kullanilir(self):
        ip = self.adaptor.get_client_ip(self._istek(HTTP_X_REAL_IP="203.0.113.10"))
        self.assertEqual(ip, "203.0.113.10")

    @override_settings(BEHIND_PROXY=True)
    def test_eklemeli_baslikta_en_sagdaki_alinir(self):
        """
        Eklemeli biçimde gerçek istemci EN SAĞDA olur.

        Bu test bir dönem bunun tersini doğruluyordu: "başlık bir gün
        eklemeli hâle gelirse gerçek istemci en solda olur" deyip en soldaki
        değeri bekliyordu. nginx'in eklemeli biçimi
        ($proxy_add_x_forwarded_for) istemcinin gönderdiği değerin ARDINA
        kendi gördüğü adresi ekliyor:

            X-Forwarded-For: <istemcinin uydurduğu>, <nginx'in gördüğü>

        Yani en soldaki değer saldırganın yazdığı şey. Eski hâliyle kod da
        test de, korunmaya çalışılan durumda saldırganın seçtiği adresi
        doğru sayıyordu: allauth'un giriş hız sınırı her istekte başka bir
        "IP" göstererek atlanabilir, başka birinin adresi kilitletilebilirdi.
        """
        ip = self.adaptor.get_client_ip(
            self._istek(HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.11")
        )
        self.assertEqual(ip, "203.0.113.11")

    @override_settings(BEHIND_PROXY=True)
    def test_iki_hiz_sinirlama_yolu_ayni_adresi_goruyor(self):
        """
        allauth ile apps/core/ratelimit.py aynı IP'yi bulmalı.

        Ayrı ayrı yazıldıkları için bir dönem biri soldan, diğeri sağdan
        okuyordu. Aynı isteğe iki farklı adres demeleri, sınırlardan birinin
        yanlış sayması demek.
        """
        from apps.core.ratelimit import istemci_ip

        istek = self._istek(HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.11")
        self.assertEqual(self.adaptor.get_client_ip(istek), istemci_ip(istek))

    @override_settings(BEHIND_PROXY=False)
    def test_vekil_yokken_iletilen_baslik_kullanilmaz(self):
        """
        Vekil arkasında değilken X-Forwarded-For'a GÜVENİLMEZ; istemci onu
        kendisi uydurabilir. Bu durumda REMOTE_ADDR esas alınmalı.
        """
        istek = self.fabrika.post("/hesap/login/")
        istek.META["REMOTE_ADDR"] = "198.51.100.5"
        istek.META["HTTP_X_FORWARDED_FOR"] = "1.2.3.4"
        self.assertEqual(self.adaptor.get_client_ip(istek), "198.51.100.5")

    @override_settings(BEHIND_PROXY=True)
    def test_giris_sayfasina_post_403_vermez(self):
        """Asıl belirti: Unix soketi arkasında giriş POST'u 403 dönüyordu."""
        kullanici("ozan@example.com", "Ozan Kaya")
        yanit = self.client.post(
            reverse("account_login"),
            {"login": "ozan@example.com", "password": "CokGuvenliParola123"},
            REMOTE_ADDR="",
            HTTP_X_FORWARDED_FOR="203.0.113.12",
        )
        self.assertNotEqual(yanit.status_code, 403, "Giriş POST'u 403 döndü")


class ArayuzMetniTesti(TestCase):
    """
    Arayüz metni kuralları.

    Django'nun {# ... #} açıklaması **yalnızca tek satırda** çalışır: şablon
    ayrıştırıcısının deseni satır sonuna geçmediği için, açıklama alt satıra
    taşarsa açıklama sayılmaz ve sayfada düz metin olarak görünür. Bu bir kez
    yaşandığı için kalıcı olarak kontrol ediyoruz. Çok satırlı açıklama gerekiyorsa
    {% comment %} kullanılmalı.
    """

    SABLON_KOKU = settings.BASE_DIR / "templates"

    def _sablonlar(self):
        return sorted(self.SABLON_KOKU.rglob("*.html"))

    def test_cok_satirli_kisa_aciklama_yok(self):
        hatali = []
        for yol in self._sablonlar():
            for no, satir in enumerate(yol.read_text(encoding="utf-8").splitlines(), 1):
                if "{#" in satir and "#}" not in satir.split("{#", 1)[1]:
                    hatali.append(f"{yol.relative_to(self.SABLON_KOKU)}:{no}")
        self.assertEqual(
            hatali,
            [],
            "Çok satırlı {# #} açıklaması sayfada düz metin olarak görünür. "
            "{% comment %} kullanın. Sorunlu satırlar: " + ", ".join(hatali),
        )

    def test_sablonlarda_uzun_tire_yok(self):
        """Uzun tire (—) arayüzde kullanılmıyor; yerine nokta, virgül ya da noktalı virgül."""
        hatali = []
        for yol in self._sablonlar():
            for no, satir in enumerate(yol.read_text(encoding="utf-8").splitlines(), 1):
                if "—" in satir or "–" in satir:
                    hatali.append(f"{yol.relative_to(self.SABLON_KOKU)}:{no}")
        self.assertEqual(hatali, [], "Uzun tire bulundu: " + ", ".join(hatali))

    def test_render_edilen_sayfalarda_sizinti_yok(self):
        """Gerçek çıktıda ne açıklama kalıntısı ne de uzun tire olmalı."""
        ozan = kullanici("ozan@example.com", "Ozan Kaya")
        grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=ozan)
        Uyelik.objects.create(
            grup=grup, kullanici=ozan, rol=Uyelik.Rol.YONETICI, durum=Uyelik.Durum.ONAYLI
        )
        mac = Mac.objects.create(
            grup=grup,
            baslangic=timezone.now() - timezone.timedelta(days=1),
            olusturan=ozan,
        )
        Katilim.objects.create(mac=mac, kullanici=ozan, yanit=Katilim.Yanit.GELIYORUM)

        misafir_yollari = [reverse("core:home"), reverse("account_login")]
        for yol in misafir_yollari:
            with self.subTest(yol=yol):
                govde = self.client.get(yol).content.decode("utf-8")
                self.assertNotIn("{#", govde)
                self.assertNotIn("#}", govde)
                self.assertNotIn("—", govde)

        self.client.force_login(ozan)
        uye_yollari = [
            reverse("core:dashboard"),
            reverse("groups:detay", args=[grup.genel_id]),
            reverse("groups:davetler", args=[grup.genel_id]),
            reverse("matches:detay", args=[mac.pk]),
            reverse("ratings:puanla", args=[mac.pk]),
            reverse("chat:sohbet", args=[grup.genel_id]),
            reverse("chat:anahtar_kurulumu"),
            reverse("accounts:profil", args=[ozan.pk]),
        ]
        for yol in uye_yollari:
            with self.subTest(yol=yol):
                govde = self.client.get(yol).content.decode("utf-8")
                self.assertNotIn("{#", govde, f"{yol} çıktısında açıklama kalıntısı var")
                self.assertNotIn("#}", govde, f"{yol} çıktısında açıklama kalıntısı var")
                self.assertNotIn("—", govde, f"{yol} çıktısında uzun tire var")


class HesapSayfalariStiliTesti(TestCase):
    """
    Hesap ekranlarının çıplak HTML'e düşmediğini doğrular.

    allauth sayfalarının şablonları pakete ait olduğu için stilleri
    "hesap-sayfasi" sarmalayıcısı ve elements/ altındaki geçersiz kılmalar
    üzerinden alıyor. Bu bağ kopunca sayfa sessizce stilsiz kalıyordu.
    """

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.client.force_login(self.ozan)

    def test_profil_duzenlemede_yonlendirmeler_stilli(self):
        govde = self.client.get(reverse("accounts:profil_duzenle")).content.decode("utf-8")
        # Hesap ayarı bağlantıları düz <a> değil, tasarlanmış satır olmalı.
        # Toplam sayı sabitlenmiyor; ayar eklendiğinde test kırılmasın diye
        # her ayarın stilli satır olarak basıldığı tek tek aranıyor.
        for yol in [
            reverse("account_change_password"),
            reverse("account_email"),
            reverse("socialaccount_connections"),
            reverse("chat:anahtar_kurulumu"),
            reverse("accounts:hesabimi_sil"),
        ]:
            with self.subTest(yol=yol):
                self.assertIn(f'<a class="ayar-satiri" href="{yol}"', govde)
        self.assertIn("ayar-ok", govde)
        self.assertIn("kutu-baslik", govde)
        # Form kart içinde dursun.
        self.assertIn('class="kutu"', govde)

    def test_allauth_sayfalari_defter_kabugunu_aliyor(self):
        for yol in [
            reverse("account_change_password"),
            reverse("account_email"),
            reverse("socialaccount_connections"),
        ]:
            with self.subTest(yol=yol):
                yanit = self.client.get(yol)
                self.assertEqual(yanit.status_code, 200)
                govde = yanit.content.decode("utf-8")
                self.assertIn("hesap-sayfasi", govde)
                # allauth'un varsayılan form.as_p çıktısına düşmemeli.
                self.assertNotIn("as_p", govde)

    def test_allauth_formlari_defter_alan_yapisini_kullaniyor(self):
        govde = self.client.get(reverse("account_change_password")).content.decode("utf-8")
        self.assertIn('class="alan"', govde)
        self.assertIn("dugme", govde)

    def test_stil_dosyasi_gerekli_bilesenleri_iceriyor(self):
        css = (settings.BASE_DIR / "static" / "css" / "defter.css").read_text(encoding="utf-8")
        for secici in [
            "\nhr {",
            "details > summary",
            "::file-selector-button",
            ".ayar-satiri",
            ".hesap-sayfasi",
            ".alan-yardim ul",
        ]:
            with self.subTest(secici=secici):
                self.assertIn(secici, css, f"defter.css içinde {secici} yok")

    def test_saha_parmakla_kaydirmayi_engellemiyor(self):
        """
        Telefonda sahaya dokunan sayfayı kaydırabilmeli.

        Eskiden `.saha` ve `.oyuncu-kart` için koşulsuz `touch-action: none`
        yazıyordu; saha ekranın yarısını kapladığı için parmağını oraya koyan
        kimse sayfayı kaydıramıyordu. Artık yalnızca düzenleme ekranındaki
        kartlar parmağı yakalıyor: oyuncunun üstünden başlayan hareket
        sürükleme, sahanın boşundan başlayan hareket kaydırma.
        """
        import re

        css = (settings.BASE_DIR / "static" / "css" / "defter.css").read_text(
            encoding="utf-8"
        )
        # Açıklamalar çıkarılıyor: "eskiden touch-action: none vardı" diyen
        # bir yorum kuralın kendisi sanılmasın.
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

        # Kuralın hangi bloklarda geçtiğine bakılıyor.
        bloklar = {}
        for ham in css.split("}"):
            if "{" not in ham:
                continue
            secici, govde = ham.rsplit("{", 1)
            bloklar[secici.strip().splitlines()[-1].strip()] = govde

        kilitli = [
            secici
            for secici, govde in bloklar.items()
            if "touch-action: none" in govde
        ]

        self.assertNotIn(".saha", kilitli, "saha tüm dokunuşları yutuyor")
        self.assertNotIn(".oyuncu-kart", kilitli, "kartlar salt okunurken de yutuyor")
        self.assertIn(
            ".saha[data-duzenlenebilir] .oyuncu-kart",
            kilitli,
            "düzenleme ekranında kart sürüklenirken sayfa kaymamalı",
        )


class ProfilTesti(TestCase):
    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")

    def test_profil_olusturuluyor(self):
        self.assertTrue(hasattr(self.ozan, "profil"))

    def test_profil_misafire_kapali(self):
        yanit = self.client.get(reverse("accounts:profil", args=[self.ozan.pk]))
        self.assertEqual(yanit.status_code, 404)

    @override_settings(PUBLIC_PROFILES=True)
    def test_profil_acik_ayarla_gorunur(self):
        yanit = self.client.get(reverse("accounts:profil", args=[self.ozan.pk]))
        self.assertEqual(yanit.status_code, 200)

    def test_profil_duzenleme_adi_gunceller(self):
        self.client.force_login(self.ozan)
        yanit = self.client.post(
            reverse("accounts:profil_duzenle"),
            {"ad_soyad": "Ozan K.", "mevki": "forvet", "forma_no": "10", "hakkinda": "Sol ayak"},
        )
        self.assertEqual(yanit.status_code, 302)
        self.ozan.refresh_from_db()
        self.assertEqual(self.ozan.ad_soyad, "Ozan K.")
        self.assertEqual(self.ozan.profil.forma_no, 10)

    def test_gecersiz_forma_no_reddedilir(self):
        self.client.force_login(self.ozan)
        self.client.post(
            reverse("accounts:profil_duzenle"),
            {"ad_soyad": "Ozan", "mevki": "", "forma_no": "250", "hakkinda": ""},
        )
        self.ozan.profil.refresh_from_db()
        self.assertIsNone(self.ozan.profil.forma_no)


class GuvenlikIncelemesiTesti(TestCase):
    """
    Ağustos 2026 güvenlik incelemesinde bulunan sorunlar.

    Her test bir bulguya karşılık geliyor; ayrıntılar
    deploy/play/test-bulgulari.md dosyasının "E. Security review" bölümünde.
    """

    # -- E1: çevrimdışı sayfası --------------------------------------------
    def test_cevrimdisi_sayfasi_girisliyken_de_kisisel_veri_icermiyor(self):
        """
        Asıl bulgu buydu.

        Servis çalışanı çevrimdışı sayfasını KURULUM anında indirip cihazda
        saklıyor ve kurulum, kullanıcı giriş yapmışken oluyor. cache.add()
        varsayılan olarak çerez gönderdiği için sunucu sayfayı o kullanıcı
        için render ediyordu: diske düşen kopyada CSRF jetonu, kullanıcının
        kimliği, okunmamış bildirim sayısı ve çıkış formu vardı. Çıkış
        yapmak önbelleği temizlemiyor, kopya cihazda kalıyordu.

        Eski test yalnızca giriş yapılmamış hâli kontrol ediyordu, bu yüzden
        sorunu göremiyordu. Kritik olan istek tam da bu: çerezli istek.
        """
        oyuncu = kullanici("cevrimdisi@example.com", "Test Oyuncu")
        self.client.force_login(oyuncu)

        govde = self.client.get(reverse("core:cevrimdisi")).content.decode("utf-8")

        self.assertNotIn("csrfmiddlewaretoken", govde, "CSRF jetonu cihazda saklanıyor")
        self.assertNotIn(f"/profil/{oyuncu.pk}/", govde, "Kullanıcı kimliği sızıyor")
        self.assertNotIn("account_logout", govde)
        self.assertNotIn("Çıkış", govde)
        # Sayfanın kendisi çalışmaya devam etmeli.
        self.assertIn("İnternet bağlantısı yok", govde)

    def test_cevrimdisi_sablonu_base_genisletmiyor(self):
        """
        Kural şablonun kendisinde de dursun.

        base.html içinde tema formu ve çıkış formu var, ikisi de CSRF jetonu
        basıyor. Sayfa base'i genişlettiği sürece çerezsiz indirmek tek
        başına yetmez, çünkü sayfa bir gün yine çerezli indirilebilir.
        """
        yol = settings.BASE_DIR / "templates" / "core" / "cevrimdisi.html"
        kaynak = yol.read_text(encoding="utf-8")
        self.assertNotIn("{% extends", kaynak)
        self.assertNotIn("csrf_token", kaynak)

    def test_servis_calisani_cevrimdisi_sayfasini_cerezsiz_indiriyor(self):
        govde = self.client.get("/sw.js").content.decode("utf-8")
        self.assertIn("credentials", govde)
        self.assertIn("omit", govde)

    def test_cevrimdisi_sayfasinin_hic_betigi_yok(self):
        """
        Çevrimdışı sayfası JavaScript'e bağlı olmamalı.

        Üretimde statik dosya adları karma taşıyor. app.js içindeki
        "import ./e2ee.js" karmasız adrese düşüyor, o adres önbellekte
        bulunmuyor ve çevrimdışıyken modül yüklemesi çöküyordu: sayfadaki
        tek etkileşim olan "Yeniden dene" düğmesi tam da işe yarayacağı
        anda ölüydü. Sayfa artık betiksiz; yenileme, action'ı boş bir GET
        formuyla yapılıyor.
        """
        govde = self.client.get(reverse("core:cevrimdisi")).content.decode("utf-8")
        self.assertNotIn("<script", govde)
        self.assertIn("Yeniden dene", govde)

    # -- E2: çıkışta şifreleme deposu --------------------------------------
    def test_sayfa_sifreleme_deposunun_sahibini_bildiriyor(self):
        """
        Çözülmüş sohbet anahtarları IndexedDB içinde kalıcı duruyordu ve
        çıkış yapmak onları silmiyordu. Tek temizleme yolu sohbet
        sayfasındaki "Bu tarayıcıda kilitle" düğmesiydi; çıkış yapan birinin
        ona basmak için hiçbir sebebi yok.

        Artık her sayfa gövdesi deponun kime ait olması gerektiğini
        söylüyor, app.js uyuşmazlıkta depoyu siliyor.
        """
        oyuncu = kullanici("depo@example.com", "Depo Testi")

        misafir = self.client.get(reverse("core:home")).content.decode("utf-8")
        self.assertIn('data-oturum="kapali"', misafir)

        self.client.force_login(oyuncu)
        girisli = self.client.get(reverse("core:dashboard")).content.decode("utf-8")
        self.assertIn(f'data-kullanici-id="{oyuncu.pk}"', girisli)
        self.assertNotIn('data-oturum="kapali"', girisli)

    def test_depo_sabitleri_iki_dosyada_ayni(self):
        """
        Denetim app.js'de, deponun kendisi e2ee.js'de.

        app.js her sayfada yükleniyor; yalnızca bu denetim için sohbet
        modülünü de her sayfaya çektirmek gereksiz bir istek olurdu. Bedeli,
        veritabanı sabitlerinin iki dosyada durması. Ayrı düşerlerse app.js
        yanlış veritabanını temizler ya da e2ee.js nesne deposunu hiç
        bulamaz; ikisi de sessiz bozulma.
        """
        import re

        kok = settings.BASE_DIR / "static" / "js"
        e2ee = (kok / "e2ee.js").read_text(encoding="utf-8")
        uygulama = (kok / "app.js").read_text(encoding="utf-8")

        def deger(kaynak, ad):
            eslesme = re.search(rf"const {ad} = (.+?);", kaynak)
            self.assertIsNotNone(eslesme, f"{ad} bulunamadı")
            return eslesme.group(1)

        for e2ee_adi, app_adi in [
            ("DB_ADI", "E2EE_DB_ADI"),
            ("DEPO_ADI", "E2EE_DEPO_ADI"),
            ("DB_SURUM", "E2EE_DB_SURUM"),
            ("SAHIP_ANAHTARI", "E2EE_SAHIP_ANAHTARI"),
        ]:
            with self.subTest(sabit=e2ee_adi):
                self.assertEqual(deger(e2ee, e2ee_adi), deger(uygulama, app_adi))

    def test_app_js_sohbet_modulunu_her_sayfaya_cekmiyor(self):
        """Denetim uğruna kripto modülü her sayfaya inmemeli."""
        uygulama = (settings.BASE_DIR / "static" / "js" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import ", uygulama)
        self.assertIn("sifrelemeDeposunuDenetle", uygulama)

    # -- E6: bildirim hedefi ------------------------------------------------
    def test_bildirim_hedefi_disari_yonlendiremez(self):
        """
        okundu_isaretle() doğrudan guvenli_url adresine yönlendiriyor.

        Yalnızca eğik çizgiyle başlamayı aramak yetmiyordu: tarayıcılar ters
        bölüyü eğik çizgi gibi okuduğu için ters bölüyle başlayan adres
        protokole göreli bir adrese dönüşüyor. Satır sonu taşıyan adres de
        Location başlığına başlık enjekte edebilirdi.
        """
        from apps.notifications.models import Bildirim

        for yol in ["/panel/", "/gruplar/", "/"]:
            with self.subTest(yol=yol):
                self.assertEqual(Bildirim(hedef_url=yol).guvenli_url, yol)

        reddedilecek = [
            "//baska.site/",
            "/" + chr(92) + "baska.site/",
            "https://baska.site/",
            "javascript:alert(1)",
            "/panel/" + chr(10) + "Set-Cookie: a=b",
            "/panel/" + chr(13),
            "/panel/" + chr(127),
            "",
        ]
        for yol in reddedilecek:
            with self.subTest(yol=repr(yol)):
                self.assertEqual(Bildirim(hedef_url=yol).guvenli_url, "")

    # -- E3 / E4: üretim ayarı denetimleri ---------------------------------
    @override_settings(DEBUG=False, ACCOUNT_EMAIL_VERIFICATION="none")
    def test_uretimde_kapali_eposta_dogrulamasi_uyari_veriyor(self):
        from apps.core.checks import eposta_dogrulamasi_acik_mi

        uyarilar = eposta_dogrulamasi_acik_mi(None)
        self.assertEqual([u.id for u in uyarilar], ["halisaha.W001"])

    @override_settings(DEBUG=False, ACCOUNT_EMAIL_VERIFICATION="mandatory")
    def test_dogrulama_zorunluyken_uyari_yok(self):
        from apps.core.checks import eposta_dogrulamasi_acik_mi

        self.assertEqual(eposta_dogrulamasi_acik_mi(None), [])

    @override_settings(DEBUG=True, ACCOUNT_EMAIL_VERIFICATION="none")
    def test_gelistirmede_dogrulama_uyarisi_cikmiyor(self):
        from apps.core.checks import eposta_dogrulamasi_acik_mi

        self.assertEqual(eposta_dogrulamasi_acik_mi(None), [])

    @override_settings(
        DEBUG=False,
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    )
    def test_surec_basina_onbellek_uyari_veriyor(self):
        """
        Hız sınırları Django önbelleğini kullanıyor, varsayılan LocMemCache
        ise süreç başına ayrı bir sözlük. deploy/gunicorn.conf.py beş işçi
        başlatıyor, yani 5/5m/ip yazan giriş sınırı pratikte 25/5m/ip
        oluyor. README bunu anlatıyordu ama ayarın yapıldığını kimse
        denetlemiyordu.
        """
        from apps.core.checks import hiz_siniri_onbellegi_paylasimli_mi

        uyarilar = hiz_siniri_onbellegi_paylasimli_mi(None)
        self.assertEqual([u.id for u in uyarilar], ["halisaha.W002"])

    @override_settings(
        DEBUG=False,
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://127.0.0.1:6379",
            }
        },
    )
    def test_paylasimli_onbellekte_uyari_yok(self):
        from apps.core.checks import hiz_siniri_onbellegi_paylasimli_mi

        self.assertEqual(hiz_siniri_onbellegi_paylasimli_mi(None), [])

    def test_denetimler_yalnizca_deploy_ile_calisiyor(self):
        from django.core.checks import registry

        deploy_ile = {
            f.__name__
            for f in registry.registry.get_checks(include_deployment_checks=True)
        }
        self.assertIn("eposta_dogrulamasi_acik_mi", deploy_ile)
        self.assertIn("hiz_siniri_onbellegi_paylasimli_mi", deploy_ile)

        gunluk = {f.__name__ for f in registry.registry.get_checks()}
        self.assertNotIn("eposta_dogrulamasi_acik_mi", gunluk)

    def test_guncelleme_betigi_uyariya_takilip_durmuyor(self):
        """
        Uyarı, yayına almayı DURDURMAMALI.

        Bu iki denetim eklendiğinde deploy/guncelle.sh içinde
        "check --deploy --fail-level WARNING" yazıyordu. Django'nun kendi
        kontrolleri o sırada temiz olduğu için satır yıllarca sorun
        çıkarmamıştı; yeni uyarılar gelince komut 1 dönmeye başladı ve
        "set -e" betiği tam o satırda öldürdü.

        Sonuç, teşhis edilmesi zor bir durumdu: "git pull" çalışmış,
        "systemctl restart" hiç çalışmamıştı. Yeni kod diskteydi, gunicorn
        modülleri süreç açılışında belleğe aldığı için ESKİ kodu servis
        etmeye devam ediyordu. Site ayaktaydı, dağıtım yapılmış
        görünüyordu, yalnızca değişiklikler ortada yoktu.

        Uyarı "şunu da halletmelisin" notudur; gerçek hatadan ayrı tutulmalı.
        """
        betik = (settings.BASE_DIR / "deploy" / "guncelle.sh").read_text(
            encoding="utf-8"
        )

        calisan_satirlar = [
            satir for satir in betik.splitlines()
            if satir.strip() and not satir.lstrip().startswith("#")
        ]
        kod = "\n".join(calisan_satirlar)

        self.assertNotIn(
            "--fail-level WARNING", kod,
            "Uyarı yayına almayı durduruyor; servis yeniden başlatılmadan "
            "betik ölür ve sunucu eski kodu çalıştırmaya devam eder.",
        )
        # Denetim yine de çalışmalı: sessizce atlanmış olmasın.
        self.assertIn("check --deploy", kod)
        # Ve yeniden başlatma adımı hâlâ yerinde olmalı.
        self.assertIn("systemctl restart halisaha", kod)

    def test_guncelleme_betigi_sessizce_olmuyor(self):
        """
        Betik ortada ölürse bunu söylemeli.

        Asıl tuzak buydu: "set -e" ile betik sessizce kapanıyordu ve
        yayına alınmadığını anlamanın tek yolu, en sonda basılan "Yayında"
        satırının YOKLUĞUNU fark etmekti.
        """
        betik = (settings.BASE_DIR / "deploy" / "guncelle.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("trap", betik)
        self.assertIn("YENİDEN BAŞLATILMADI", betik)


class AcikBulgularTesti(TestCase):
    """
    Henüz kapatılmamış bulgular (E8, E9) ve kapatılan E7'nin nöbetçisi.

    Buradaki testler bir düzeltmeyi değil, bilinen bir açığın bugünkü
    davranışını sabitliyor. Amaçları iki tane:

      1. Bulgunun gerçekten var olduğunu kanıtlamak (belge iddiada
         bulunmuyor, test gösteriyor).
      2. Davranış değişirse haber vermek. Biri açığı kapattığında test
         kırılır ve bu dosyayla belgenin birlikte güncellenmesi gerekir.

    Bir test kırıldığında yapılacak şey onu düzeltmek değil,
    deploy/play/test-bulgulari.md içindeki ilgili satırı "kapatıldı"ya
    çevirmek.
    """

    def setUp(self):
        self.yonetici = kullanici("yonetici@example.com", "Grup Yöneticisi")
        self.oyuncular = [kullanici(f"a{i}@example.com", f"Oyuncu {i}") for i in range(4)]
        self.grup = Grup.objects.create(ad="İnceleme Ekibi", kurucu=self.yonetici)
        Uyelik.objects.create(
            grup=self.grup,
            kullanici=self.yonetici,
            rol=Uyelik.Rol.YONETICI,
            durum=Uyelik.Durum.ONAYLI,
        )
        for k in self.oyuncular:
            Uyelik.objects.create(
                grup=self.grup,
                kullanici=k,
                rol=Uyelik.Rol.UYE,
                durum=Uyelik.Durum.ONAYLI,
            )
        self.mac = Mac.objects.create(
            grup=self.grup,
            baslangic=timezone.now() - timezone.timedelta(hours=6),
            olusturan=self.yonetici,
        )
        for k in [self.yonetici, *self.oyuncular]:
            Katilim.objects.create(
                mac=self.mac, kullanici=k, yanit=Katilim.Yanit.GELIYORUM, katildi=True
            )

    def test_acik_e8_yonetici_oy_vermeden_puanlari_gorebiliyor(self):
        """
        AÇIK BULGU E8 — yönetici ayrıcalığı puan kapısını atlıyor.

        B1 ve B2'de kapatılan şey şuydu: kimse kendi oyunu vermeden
        başkalarının ortalamasına bakıp ona göre oy veremesin.
        puan_gorunurlugu() grup yöneticisini bu kuraldan muaf tutuyor, ama
        yönetici de sahaya çıkan ve puanlanan bir oyuncu. Yani hiç oy
        vermeden herkesin ortalamasını görüp ondan sonra oy verebiliyor —
        tam olarak engellenmek istenen davranış.

        Yöneticiliğin kendisi az bulunur bir şey değil: 24 kişilik bir
        grupta yönetici sayısına sınır yok ve rol tek tıkla veriliyor.
        """
        from apps.ratings.gorunurluk import puan_gorunurlugu

        # Diğerleri birbirini puanlasın, yönetici hiç oy vermesin.
        for veren in self.oyuncular:
            for hedef in self.oyuncular:
                if veren.pk != hedef.pk:
                    Puan.objects.create(
                        mac=self.mac, puanlayan=veren, puanlanan=hedef, deger=7
                    )

        sade_uye = puan_gorunurlugu(self.mac, self.oyuncular[0])
        self.assertFalse(
            sade_uye.gorebilir,
            "Sade üye yöneticiyi puanlamadığı için görememeli",
        )

        yonetici_durumu = puan_gorunurlugu(self.mac, self.yonetici)
        self.assertTrue(
            yonetici_durumu.gorebilir,
            "AÇIK BULGU KAPATILMIŞ: yönetici artık oy vermeden göremiyor. "
            "test-bulgulari.md içindeki E8 satırını kapatıldı olarak güncelle.",
        )
        self.assertTrue(yonetici_durumu.yonetici_ayricaligi)
        self.assertEqual(
            Puan.objects.filter(mac=self.mac, puanlayan=self.yonetici).count(),
            0,
            "Yönetici tek bir oy bile vermemişti",
        )

    def test_acik_e9_davet_jetonu_url_yolunda_tasiniyor(self):
        """
        AÇIK BULGU E9 — ham davet jetonu erişim günlüklerine düşüyor.

        Model, jetonu bilerek saklamıyor: veritabanında yalnızca SHA-256
        özeti var, gerekçesi de "veritabanı sızsa bile çalışan davet
        bağlantısı üretilemez". Ama bağlantının kendisi jetonu URL YOLUNDA
        taşıyor ve bu yol iki ayrı yere düz metin olarak yazılıyor:

          * nginx erişim günlüğü (location / bloğunda access_log kapalı değil)
          * gunicorn access_log_format içindeki %(r)s alanı

        Jeton varsayılan olarak 7 gün ve 25 kullanım geçerli. Yani günlük
        okuyabilen biri (log toplayıcı, yedek, destek erişimi) çalışan davet
        bağlantısı elde ediyor — özet saklamanın engellemek istediği şeyin
        aynısı, başka bir kapıdan.
        """
        davet, ham_jeton = DavetBagi.olustur(
            grup=self.grup, olusturan=self.yonetici, gun=7, max_kullanim=25
        )

        # Özet saklanıyor, ham jeton saklanmıyor: burası doğru çalışıyor.
        self.assertNotEqual(davet.jeton_ozet, ham_jeton)
        self.assertEqual(davet.jeton_ozet, jeton_ozeti(ham_jeton))

        adres = reverse("groups:davet_ile_katil", kwargs={"jeton": ham_jeton})
        self.assertIn(
            ham_jeton,
            adres,
            "AÇIK BULGU KAPATILMIŞ: jeton artık URL yolunda değil. "
            "test-bulgulari.md içindeki E9 satırını kapatıldı olarak güncelle.",
        )

    def test_e7_kapandi_sohbet_acik_anahtari_dogruluyor(self):
        """
        E7 KAPATILDI — sohbet artık açık anahtarı doğruluyor.

        Bu test bir dönem bunun TERSİNİ sabitliyordu: sohbet arayüzünün
        parmak izine hiç bakmadığını ve sunucunun istemciden gelen parmak
        izini olduğu gibi sakladığını doğruluyordu. İkisi de düzeltildi,
        dolayısıyla test de tersine çevrildi.

        Kalan sınır, kapatılamayan türden: ilk görülen anahtara güveniliyor.
        Yeni bir cihaz, sunucunun o an verdiği anahtarı doğru kabul eder.
        Kesinlik ancak iki kişinin parmak izlerini yüz yüze
        karşılaştırmasıyla gelir; arayüz parmak izlerini bu yüzden
        gösteriyor.
        """
        from apps.chat.models import AnahtarCifti
        from apps.chat.services import parmak_izi_hesapla

        kaynak = (settings.BASE_DIR / "static" / "js" / "sohbet.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("acikAnahtariDenetle", kaynak)
        self.assertIn("parmakIzleriniYaz", kaynak)

        # Sunucu artık parmak izini istemciden almıyor, anahtardan hesaplıyor.
        jwk = {"kty": "RSA", "alg": "RSA-OAEP-256", "n": "AAAA", "e": "AQAB"}
        self.client.force_login(self.yonetici)
        yanit = self.client.post(
            reverse("chat:api_kendi_anahtarim"),
            data=json.dumps({
                "acik_anahtar": jwk,
                "sifreli_ozel_anahtar": "QUJDRA==",
                "tuz": "QUJDRA==",
                "iv": "QUJDRA==",
                "yineleme": 600000,
                "parmak_izi": "tamamen uydurma bir deger",
            }),
            content_type="application/json",
        )
        self.assertEqual(yanit.status_code, 200)

        kayit = AnahtarCifti.objects.get(kullanici=self.yonetici)
        self.assertEqual(kayit.parmak_izi, parmak_izi_hesapla(jwk))
        self.assertNotIn("uydurma", kayit.parmak_izi)


class AnahtarDogrulamaTesti(TestCase):
    """
    Sohbette açık anahtar doğrulaması (E7 bulgusunun kapatılması).

    Sunucu artık parmak izini istemciden almıyor, saklanan açık anahtardan
    hesaplıyor; tarayıcı da üyelerin anahtarlarını ilk gördüğü hâliyle
    sabitleyip değiştiğinde grup anahtarını sarmalamayı reddediyor.
    """

    # static/js/e2ee.js içindeki aynı vektörle üretilen değer. İki dil ayrı
    # düşerse kullanıcı ekranda gördüğü parmak izini karşı tarafınkiyle
    # karşılaştıramaz; bu testin tamamı bunun içindir.
    VEKTOR = {"n": "sahte-modulus-degeri-123", "e": "AQAB"}
    BEKLENEN = "C7F5 3AAD 10C3 328D E4D2 1AF8 4AEA 102B"

    def setUp(self):
        self.ozan = kullanici("ozan@example.com", "Ozan Kaya")
        self.mert = kullanici("mert@example.com", "Mert Yılmaz")
        self.grup = Grup.objects.create(ad="Perşembe Ekibi", kurucu=self.ozan)
        for k in (self.ozan, self.mert):
            Uyelik.objects.create(
                grup=self.grup, kullanici=k,
                rol=Uyelik.Rol.UYE, durum=Uyelik.Durum.ONAYLI,
            )

    def _anahtar_olustur(self, kisi, n):
        from apps.chat.models import AnahtarCifti
        from apps.chat.services import parmak_izi_hesapla

        jwk = {"kty": "RSA", "alg": "RSA-OAEP-256", "n": n, "e": "AQAB"}
        return AnahtarCifti.objects.create(
            kullanici=kisi,
            acik_anahtar=json.dumps(jwk, separators=(",", ":")),
            sifreli_ozel_anahtar="QUJDRA==",
            tuz="QUJDRA==", iv="QUJDRA==", yineleme=600000,
            parmak_izi=parmak_izi_hesapla(jwk),
        )

    # -- Parmak izi hesabı -------------------------------------------------
    def test_parmak_izi_sabit_vektor(self):
        from apps.chat.services import parmak_izi_hesapla

        self.assertEqual(parmak_izi_hesapla(self.VEKTOR), self.BEKLENEN)

    def test_parmak_izi_bicimi(self):
        """Sekiz öbek, dörder karakter. Sesli okunacak biçim."""
        from apps.chat.services import parmak_izi_hesapla

        iz = parmak_izi_hesapla({"n": "baska-bir-modulus", "e": "AQAB"})
        self.assertRegex(iz, r"^([0-9A-F]{4} ){7}[0-9A-F]{4}$")

    def test_farkli_anahtar_farkli_parmak_izi(self):
        from apps.chat.services import parmak_izi_hesapla

        self.assertNotEqual(
            parmak_izi_hesapla(self.VEKTOR),
            parmak_izi_hesapla({"n": "bambaska", "e": "AQAB"}),
        )

    # -- Sunucu istemciye güvenmiyor ---------------------------------------
    def test_sunucu_istemcinin_parmak_izini_yok_sayiyor(self):
        """
        Asıl düzeltme.

        Eskiden gövdedeki parmak_izi olduğu gibi saklanıyordu, yani kayıt
        kendi kendini doğruluyordu: anahtarla parmak izi birbirini tutmak
        zorunda değildi. Artık parmak izi her zaman saklanan anahtardan
        türüyor.
        """
        from apps.chat.models import AnahtarCifti

        self.client.force_login(self.ozan)
        yanit = self.client.post(
            reverse("chat:api_kendi_anahtarim"),
            data=json.dumps({
                "acik_anahtar": {
                    "kty": "RSA", "alg": "RSA-OAEP-256",
                    "n": self.VEKTOR["n"], "e": self.VEKTOR["e"],
                },
                "sifreli_ozel_anahtar": "QUJDRA==",
                "tuz": "QUJDRA==",
                "iv": "QUJDRA==",
                "yineleme": 600000,
                "parmak_izi": "TAMAMEN UYDURMA BIR DEGER",
            }),
            content_type="application/json",
        )
        self.assertEqual(yanit.status_code, 200)

        kayit = AnahtarCifti.objects.get(kullanici=self.ozan)
        self.assertEqual(kayit.parmak_izi, self.BEKLENEN)
        self.assertNotIn("UYDURMA", kayit.parmak_izi)

    # -- Sıfırlama kaydı ---------------------------------------------------
    def test_sifirlama_kayit_birakiyor(self):
        """
        Anahtar değişimi ile saldırıyı ayırt edebilmek için gerekli.

        Kayıt olmasa, parolasını unutup anahtarını yenileyen biriyle
        anahtarı değiştirilen biri ekranda birbirinin aynısı görünürdü.
        """
        from apps.chat.models import AnahtarDegisimi

        eski = self._anahtar_olustur(self.ozan, "ilk-modulus")
        eski_iz = eski.parmak_izi

        self.client.force_login(self.ozan)
        yanit = self.client.post(reverse("chat:api_anahtar_sifirla"))
        self.assertEqual(yanit.status_code, 200)

        kayit = AnahtarDegisimi.objects.get(kullanici=self.ozan)
        self.assertEqual(kayit.eski_parmak_izi, eski_iz)

    def test_durum_ucunda_sifirlama_zamani_donuyor(self):
        """İstemci uyarının dilini buna göre seçiyor."""
        self._anahtar_olustur(self.ozan, "ozan-modulus")
        self._anahtar_olustur(self.mert, "mert-modulus")

        self.client.force_login(self.mert)
        self.client.post(reverse("chat:api_anahtar_sifirla"))

        self.client.force_login(self.ozan)
        veri = self.client.get(
            reverse("chat:api_durum", kwargs={"genel_id": self.grup.genel_id})
        ).json()

        kayitlar = {u["id"]: u for u in veri["uyeler"]}
        self.assertIsNotNone(kayitlar[self.mert.pk]["son_sifirlama"])
        self.assertIsNone(kayitlar[self.ozan.pk]["son_sifirlama"])

    def test_durum_ucundaki_parmak_izi_anahtarla_tutuyor(self):
        """
        İstemci parmak izini kendisi hesaplıyor ama sunucununkini de
        alıyor; ikisi ayrı düşerse bu tek başına bir işaret.
        """
        from apps.chat.services import parmak_izi_hesapla

        self._anahtar_olustur(self.ozan, "ozan-modulus")
        self.client.force_login(self.ozan)
        veri = self.client.get(
            reverse("chat:api_durum", kwargs={"genel_id": self.grup.genel_id})
        ).json()

        satir = next(u for u in veri["uyeler"] if u["id"] == self.ozan.pk)
        self.assertEqual(
            satir["parmak_izi"], parmak_izi_hesapla(satir["acik_anahtar"])
        )

    # -- İstemci tarafı kancaları ------------------------------------------
    def test_istemci_sabitleme_islevlerini_sunuyor(self):
        kok = settings.BASE_DIR / "static" / "js"
        e2ee = (kok / "e2ee.js").read_text(encoding="utf-8")
        self.assertIn("export async function acikAnahtariDenetle", e2ee)
        self.assertIn("export async function parmakIziniSabitle", e2ee)
        self.assertIn("pin:", e2ee)

    def test_sohbet_sunucunun_parmak_izini_gostermiyor(self):
        """
        Ekranda GÖSTERİLEN değer her zaman yerel hesaplanan olmalı.

        Sunucunun gönderdiği dizgeyi göstermek, saldırgana kendi işini not
        ettirmek olurdu: anahtarı da parmak izini de o yazıyor.
        """
        sohbet = (settings.BASE_DIR / "static" / "js" / "sohbet.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("acikAnahtariDenetle", sohbet)
        self.assertIn("uyeleriDenetle", sohbet)
        self.assertIn("d.parmakIzi", sohbet)

    def test_degisen_anahtar_sarmalamadan_cikariliyor(self):
        """Her iki sarmalama noktasında da denetim olmalı."""
        sohbet = (settings.BASE_DIR / "static" / "js" / "sohbet.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('!== "degisti"', sohbet)
        self.assertIn('=== "degisti"', sohbet)

    def test_sohbet_sayfasinda_parmak_izi_bolumu_var(self):
        self._anahtar_olustur(self.ozan, "ozan-modulus")
        self.client.force_login(self.ozan)
        govde = self.client.get(
            reverse("chat:sohbet", kwargs={"genel_id": self.grup.genel_id})
        ).content.decode("utf-8")
        self.assertIn('id="parmak-izi-listesi"', govde)
        self.assertIn('id="anahtar-uyarisi"', govde)
