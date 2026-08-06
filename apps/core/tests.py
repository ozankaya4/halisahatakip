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
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
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

    def test_gecmis_tarihe_mac_eklenemez(self):
        self.client.force_login(self.ozan)
        geri = timezone.localtime(timezone.now() - timezone.timedelta(days=2))
        yanit = self.client.post(
            reverse("matches:olustur", args=[self.grup.genel_id]),
            {"baslangic": geri.strftime("%Y-%m-%dT%H:%M"), "sure_dakika": 60},
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

    def test_puanlama_penceresi_bir_hafta_sonra_kapanir(self):
        mac = self._oynanmis_mac()
        self.assertTrue(mac.puanlama_acik)

        mac.baslangic = timezone.now() - timezone.timedelta(days=8)
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
    def test_eklemeli_baslikta_en_soldaki_alinir(self):
        """Başlık bir gün eklemeli hâle gelirse gerçek istemci en solda olur."""
        ip = self.adaptor.get_client_ip(
            self._istek(HTTP_X_FORWARDED_FOR="203.0.113.11, 10.0.0.1")
        )
        self.assertEqual(ip, "203.0.113.11")

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
        self.assertEqual(govde.count("ayar-satiri"), 4)
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
