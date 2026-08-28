# Halısaha Defteri

Halı saha grupları için maç takibi: fikstür, yoklama anketi, maç fotoğrafları,
maç sonrası oyuncu puanlaması ve uçtan uca şifreli grup sohbeti.
Arayüz tamamen Türkçedir.

---


### Sıfırdan kurulum

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
# .env içindeki SECRET_KEY'i doldurun:
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

python manage.py migrate
python manage.py ilk_yonetici     # .env'deki SUPERADMIN_* değerlerini okur
python manage.py runserver
```

---

## Nasıl kullanılır

1. **Grup kur.** Kuran kişi otomatik olarak yönetici olur.
2. **Davet bağlantısı oluştur** (Grup → Davet bağlantıları). Bağlantı yalnızca
   bir kez gösterilir; veritabanında sadece şifreli özeti saklanır. Jeton
   adresin `#` işaretinden sonrasında durur: tarayıcılar bu parçayı sunucuya
   göndermediği için erişim günlüklerine de düşmez.
3. **Katılma isteklerini onayla.** Bağlantıyı kullanan kişi doğrudan üye olmaz —
   isteği size bildirim olarak düşer, siz onaylayana kadar grubun hiçbir
   içeriğini göremez.
4. **Maç ekle.** Tarih ve saat zorunlu, saha adı isteğe bağlı. Yoklama açıksa
   gruba bildirim gider.
5. **Maçtan sonra kadroyu işaretle** (Maç → Kadroyu işaretle). Bu liste
   puanlama yetkisini belirler.
6. **Puanla.** Herkes birbirini 10 üzerinden puanlar.
7. **Sohbet et.** İlk kullanımda bir şifreleme parolası belirlemeniz istenir.
8. **Bildirimleri aç** (Panel → Bildirimler). Maç saati değiştiğinde ya da
   yoklama açıldığında telefonunuza bildirim düşer. Sohbet bildiriminde
   mesajın kendisi yazmaz: sohbet uçtan uca şifreli olduğu için sunucu metni
   okuyamıyor, yalnızca "yeni mesaj var" diyebiliyor.
9. **İstersen sıradaki maçı cihazında sakla** (Panel → Çevrimdışı). Sahanın
   önünde çekmediğinde saat, saha ve kadro elinde olur. Varsayılan kapalı;
   yalnızca sıradaki maç saklanır, çıkışta silinir.

### Puanlama kuralları

Seçtiğiniz kurallar hem görünüm hem veritabanı seviyesinde uygulanıyor:

| Kural | Nasıl uygulanıyor |
| --- | --- |
| Yalnızca maçta oynayanlar puan verebilir | `Mac.kullanici_puanlayabilir()` |
| Kimse kendine puan veremez | Görünüm filtresi **+** `kendine_puan_verilemez` veritabanı kısıtı |
| Puanlar anonim | Arayüzde yalnızca ortalama gösterilir |
| Puanlama 3 gün sonra kapanır | `RATING_WINDOW_DAYS = 3` |
| Puanları görmek için maçtaki herkesi puanlamak gerekir | `apps/ratings/gorunurluk.py` |
| Bir oyuncuya en fazla 2 kez puan yazılır | `RATING_MAX_WRITES = 2`, `Puan.yazim_sayisi` |

Ek olarak: bir oyuncunun ortalaması, en az **3** puan toplanana kadar
gösterilmez (`RATING_MIN_VOTES_TO_DISPLAY`) — iki kişilik ortalama yanıltıcı
olduğu için. Sonuçlar da siz kendi oyunuzu verene kadar gizlidir; böylece
başkasının ortalamasına bakıp ona göre oy vermek mümkün olmaz.

**Yönetici bu kapıdan muaftır — bilinçli bir tercih.** Grup yöneticisi maç
sayfasında, sıralamada ve üye istatistiklerinde puanları kendi oyunu vermeden
de görür. Sebebi, yönetim işinin körlemesine yapılamaması: karantinaya düşen
şüpheli oyları inceleyen, yanlış girilmiş kadroyu düzelten ve şikâyetlere bakan
kişi ne olup bittiğini görmek zorunda. Yöneticiyi de kapının arkasında
bırakmak, grubu yönetmeyi imkânsız kılardı.

Muafiyetin bedeli açık: yönetici puanlara bakıp ondan sonra oy verebilir. Bu
küçük bir arkadaş grubunda kabul edilebilir bir güven varsayımı sayıldı. Karar
`apps/ratings/gorunurluk.py` içinde `yonetici_ayricaligi` olarak duruyor ve
`apps/core/tests.py::GuvenlikKararlariTesti` ile sabitlendi; biri hata sanıp
kaldırırsa test kırılıyor.

Bu değerlerin hepsi `halisaha/settings.py` sonundaki
"Uygulama kuralları" bölümünden değiştirilebilir.

---

## Google ile giriş

Varsayılan olarak kapalıdır (e-posta + parola girişi zaten çalışır).
Açmak için:

1. <https://console.cloud.google.com/apis/credentials> adresine gidin.
2. **Create Credentials → OAuth client ID → Web application** seçin.
3. **Authorized redirect URIs** kısmına şunları ekleyin:
   - Geliştirme: `http://127.0.0.1:8000/hesap/google/login/callback/`
   - Üretim: `https://ALAN-ADINIZ/hesap/google/login/callback/`
4. Aldığınız değerleri `.env` dosyasına yazın:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ```
5. Sunucuyu yeniden başlatın. Giriş sayfasında Google düğmesi görünecektir.

**Hesap birleştirme güvenliği:** Bir Google hesabı, mevcut bir yerel hesaba
yalnızca Google e-postayı **doğrulanmış** olarak bildirdiğinde ve adres yerel
tarafta da doğrulanmışsa bağlanır (`apps/accounts/adapters.py`). Aksi hâlde
biri, başkasının e-posta adresiyle sağlayıcıda hesap açıp o hesabı devralabilirdi.

---

## Güvenlik

### Genel

- **Parola saklama:** Argon2 (Django'nun varsayılan PBKDF2'sinden güçlü).
- **Brute-force koruması:** `django-axes` — 6 başarısız denemeden sonra
  kullanıcı+IP kombinasyonu 1 saat kilitlenir. Ayrıca allauth'un kendi hız
  sınırları (giriş, kayıt, parola sıfırlama) açık.
- **CSP:** Satır içi script yok, harici kaynak yok (`default-src 'none'`).
  Yazı tipleri kendi sunucumuzdan gelir; Google Fonts'a bağlanılmaz.
- **Güvenlik başlıkları:** HSTS, nosniff, `X-Frame-Options: DENY`,
  `Referrer-Policy`, COOP.
- **Dağıtım denetimleri:** `manage.py check --deploy`, Django'nun kendi
  kontrollerine ek olarak uygulamanın iki varsayımını da doğruluyor
  (`apps/core/checks.py`):
  - `halisaha.W001` — üretimde e-posta doğrulaması kapalı mı? Kapalıysa
    herkes sahibi olmadığı bir adresle kayıt olabilir.
  - `halisaha.W002` — hız sınırlama önbelleği süreç başına mı? Öyleyse
    sınırlar gunicorn işçi sayısı kadar gevşer.

  Bu ikisi bilerek uyarı veriyor: ikisi de yalnızca `.env` ve dağıtım
  yapılandırmasıyla kapatılabiliyor, kodla değil.
- **Çerezler:** HttpOnly, SameSite=Lax, HTTPS'te Secure.
- **SQL enjeksiyonu / XSS:** Django ORM ve otomatik şablon kaçışı; çözülen
  sohbet mesajları DOM'a `textContent` ile yazılır, hiçbir yerde `innerHTML` yok.
- **Açık yönlendirme:** Tema değiştirme ve bildirim bağlantıları
  `url_has_allowed_host_and_scheme` ile ya da yalnızca göreli yol kabul edilerek
  korunur.
- **Sayım saldırıları:** Gruplar URL'de sıralı kimlik yerine UUID kullanır.
- **Cihazda kalan veri:** Servis çalışanı yalnızca herkese açık statik
  dosyaları saklar; çevrimdışı sayfası kullanıcı kabuğu taşımayan ayrı bir
  şablondur ve çerezsiz indirilir, böylece cihazdaki kopyada oturuma ait
  hiçbir şey (CSRF jetonu dâhil) bulunmaz. Çözülmüş sohbet anahtarları
  IndexedDB'de durur ve giriş yapan kişi değiştiğinde silinir.

### Bildirimler ve çevrimdışı

**Telefona bildirim (Web Push).** Bildirimler eskiden yalnızca uygulama
içindeydi: kişi maçın saatinin değiştiğini ancak uygulamayı bir dahaki
açışında öğreniyordu. Artık VAPID anahtarları tanımlıysa telefona iletiliyor.

- Anahtarlar `.env` içinde (`VAPID_*`), koda gömülü değil. Üretmek için
  `python manage.py vapid_anahtari`. Anahtar yoksa özellik kendini kapatıyor
  ve arayüzde düğme hiç görünmüyor.
- İzin yalnızca kullanıcı düğmeye bastığında isteniyor; sayfa açılır açılmaz
  izin istemek tarayıcıların kalıcı retle cezalandırdığı bir davranış.
- **Sohbet bildirimi metin taşımıyor.** Sunucu şifreli mesajı okuyamıyor,
  dolayısıyla gönderemiyor da. Maç ve yoklama bildirimleri metin taşıyor,
  çünkü o metni sunucu yazıyor (`apps/notifications/push.py`).
- Ölü abonelikler (uygulama silinmiş, izin geri alınmış) ilk 404/410
  yanıtında siliniyor.

**Çevrimdışı.** Servis çalışanının kuralı "kullanıcıya ait hiçbir şey diske
yazılmaz" idi, çünkü telefon elden ele geziyor. Kural kalkmadı, daraldı:
kullanıcı panelden açarsa yalnızca **sıradaki maçın** saati, sahası ve kadrosu
cihazda saklanıyor. Puan, sohbet, fotoğraf ve geçmiş maçlar asla. Varsayılan
kapalı, çıkışta siliniyor (depo sahibi denetimiyle aynı yoldan).

### Dosya yükleme

`apps/core/images.py` içinde:

1. Boyut sınırı (8 MB) ve uzantı beyaz listesi.
2. `Pillow.verify()` ile yapı doğrulaması.
3. Gerçek biçim kontrolü — **SVG kabul edilmez** (içinde `<script>` taşıyabilir).
4. Çözünürlük sınırı ve dekompresyon bombası koruması.
5. **Her dosya WEBP olarak yeniden kodlanır.** Bu adım iki işi birden yapar:
   polyglot dosyaları (aynı anda hem geçerli resim hem çalıştırılabilir kod olan
   dosyalar) etkisiz kılar ve **EXIF verisini tamamen siler** — telefonların
   fotoğrafa gömdüğü GPS koordinatları dâhil.
6. Dosya adı kullanıcıdan hiç alınmaz, UUID üretilir. `../` ve `resim.jpg.php`
   gibi saldırılar anlamsızlaşır.

**Sunum tarafı:** Yüklenen dosyalar web kökünden doğrudan sunulmaz. URL bir
dosya yolu değil bir veritabanı kimliği taşır (`/dosya/mac/<uuid>/`), böylece
yol geçişi yapısal olarak imkânsızdır. Her istekte üyelik kontrol edilir —
maç fotoğrafını yalnızca o grubun onaylı üyeleri görebilir.

### Uçtan uca şifreleme (sohbet)

Sunucu mesaj içeriğini **okuyamaz**. Nihai yönetici de okuyamaz. Bu bilinçli
bir tercihtir ve şu sonuçları vardır:

| Algoritma | Kullanım |
| --- | --- |
| RSA-OAEP 2048 / SHA-256 | Kimlik anahtarı, grup anahtarını sarmalama |
| PBKDF2-SHA256, 600.000 tur | Şifreleme parolasından anahtar türetme |
| AES-GCM 256 | Grup anahtarı ve mesaj şifreleme |

Akış: Tarayıcı bir anahtar çifti üretir. Özel anahtar, sizin belirlediğiniz
**şifreleme parolasından** türetilen anahtarla şifrelenip sunucuya öyle yüklenir ve
parola sunucuya hiçbir zaman gitmez. Her grubun sürümlenmiş bir AES anahtarı
vardır ve bu anahtar her üye için ayrı ayrı sarmalanır. Mesajlar tarayıcıda
AES-GCM ile şifrelenir; ek doğrulanmış veri olarak `grup:sürüm:gönderen`
kullanılır, böylece sunucu bir mesajı başka gruba taşıyamaz veya göndereni
değiştiremez.

**Anahtar doğrulama.** Grup anahtarını kime sarmalayacağını söyleyen taraf
sunucudur; bu yüzden tarayıcı her üyenin açık anahtarını **ilk gördüğü hâliyle**
hatırlar. Anahtar sonradan değişirse grup anahtarı o üye için sarmalanmaz ve
sohbette adıyla birlikte bir uyarı çıkar. Uyarı, sunucuda kayıtlı bir anahtar
sıfırlaması varsa yumuşak (parolasını unutan biri için olağan), yoksa serttir.
Parmak izleri sohbet sayfasında listelenir: iki kişi bu sekiz öbeği
karşılaştırarak aralarına kimsenin girmediğini doğrulayabilir.

**Bilinçli sınırlar:**

- ⚠️ **Şifreleme parolanızı unutursanız mesaj geçmişiniz kurtarılamaz.**
  Sunucuda onu çözecek hiçbir bilgi yok. Parolayı bir parola yöneticisine kaydedin.
- Gruba yeni katılan biri, katılmadan önceki mesajları okuyamaz.
- Nihai yönetici dâhil hiç kimse sunucudan mesaj okuyamaz. (Yönetim panelinde
  yalnızca meta veri ve kötüye kullanım ihbarı için "silindi" işareti vardır;
  anahtar kayıtları salt okunur.)
- Anahtar doğrulaması "ilk görüşte güven" ilkesine dayanır: yeni bir cihaz,
  bir üyeyi ilk kez gördüğünde sunucunun verdiği anahtarı doğru kabul eder.
  Bunu kesinliğe çeviren tek şey, parmak izlerini karşı tarafla yüz yüze
  karşılaştırmaktır.
- Bir üye gruptan çıkarıldığında anahtar döner: **bundan sonraki** mesajları
  okuyamaz. Daha önce indirdiği mesajları teknik olarak geri alamayız.
- Grup anahtarını bilen bir üye, teoride başka bir üyenin adına mesaj
  şifreleyebilir. Buna karşı mesaj başına imza gerekir; bu sürümde yoktur.
  (Grup içi güven varsayımı, halı saha arkadaş grubu için makul bence.)

Sohbet, güvenli bağlam gerektirir: **HTTPS** ya da `localhost`. Düz HTTP ile
uzak bir sunucuda WebCrypto çalışmaz.

---

## Üretime alma

tek bir `.env` değişikliğiyle SQLite'tan PostgreSQL'e geçer.

### 1. `.env` ayarları

```ini
DEBUG=False
SECRET_KEY=<yeni, uzun, rastgele bir anahtar>
ALLOWED_HOSTS=halisaha.example.com
CSRF_TRUSTED_ORIGINS=https://halisaha.example.com
DATABASE_URL=postgres://kullanici:parola@sunucu:5432/halisaha
SECURE_SSL_REDIRECT=True
BEHIND_PROXY=True
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
# ... SMTP bilgileri
```

PostgreSQL için `requirements.txt` içindeki `psycopg[binary]` satırının
yorumunu kaldırıp kurun.

### 2. Dağıtım adımları

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy        # sıfır uyarı vermeli
gunicorn halisaha.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

### 3. Önbellek (önemli)

Hız sınırlama Django önbelleğini kullanır. Birden fazla worker ile
çalıştıracaksanız `CACHES` ayarını Redis/Memcached'e almalısınız; aksi hâlde
sayaçlar süreç başına tutulur ve sınırlar gevşer:

```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
    }
}
```

### 4. nginx ile korumalı dosya sunumu (isteğe bağlı)

`.env` içinde `USE_X_ACCEL_REDIRECT=True` yapın ve nginx'e ekleyin:

```nginx
location /korumali-medya/ {
    internal;                       # dışarıdan doğrudan erişilemez
    alias /uygulama/yolu/media/;
}
```

Böylece yetki kontrolünü Django yapar, dosyayı nginx gönderir.

---

## Testler

**Django tarafı:**

```powershell
.\.venv\Scripts\python.exe manage.py test
```

Sayfa render kontrollerinin yanı sıra yetki kurallarını (üye olmayan göremez,
bekleyen üye hiçbir şeyi göremez, kendine puan verilemez, maçta oynamayan
puanlayamaz, son yönetici indirilemez) ve dosya yükleme güvenliğini
(SVG reddi, sahte resim reddi, EXIF temizliği, yetkisiz erişim) doğrular.

**Şifreleme tarafı (27 kontrol):**

```powershell
node tests/e2ee-dogrula.mjs
```

`static/js/e2ee.js` içindeki **gerçek** fonksiyonları çalıştırır: anahtar
üretimi, parola ile açma, yanlış parolanın reddi, grup anahtarı sarmalama,
mesaj şifreleme/çözme ve AAD koruması (sunucunun mesajı başka gruba taşıması,
göndereni değiştirmesi ya da şifreli metni kurcalaması durumunda çözmenin
başarısız olması).

---

## Proje yapısı

```
halisaha/            Django projesi (ayarlar, kök URL)
apps/
  core/              Ortak: görsel işleme, korumalı dosya sunumu, tema, hatalar
  accounts/          Kullanıcı (e-posta ile giriş), profil, Google bağlama
  groups/            Grup, üyelik/roller, davet bağlantıları, katılma onayı
  matches/           Maç, yoklama anketi, kadro, fotoğraflar
  ratings/           Maç sonrası puanlar
  chat/              Uçtan uca şifreli sohbet (sunucu tarafı)
  notifications/     Uygulama içi bildirimler
templates/           Türkçe şablonlar
static/
  css/defter.css     "Saha Defteri" tasarım sistemi
  js/e2ee.js         Tarayıcı tarafı şifreleme
  fonts/             Fraunces + IBM Plex Sans (OFL, kendi sunucumuzdan)
```

### Tasarım notu

Arayüz **"Saha Defteri"** yönünde: kağıt zemini, mürekkep yeşili, ince cetvel
çizgileri, iri serif başlıklar (Fraunces — "WONK" ekseni açık, elle çizilmiş
hissi için) ve asimetrik yerleşim. Kutu gölgesi ve büyük köşe yuvarlaması
bilinçli olarak kullanıldı; ayrım gölgeyle değil çizgiyle ve boşlukla yapılıyor.

Açık ve koyu tema var. Tema tercihi çerezde tutulur ve sunucu tarafında
uygulanır — bu sayede sayfa açılırken yanlış temanın bir an görünmesi (flash)
yaşanmaz ve satır içi script gerekmediği için CSP sıkı kalabilir.

Yazı tipleri OFL lisanslıdır ve kendi sunucumuzdan yayınlanır: hem CSP'yi sıkı
tutabiliyoruz hem de kullanıcıların IP adresi üçüncü tarafa gitmiyor.
Türkçe için `latin-ext` alt kümesi dâhil edildi (ğ, ş, İ, Ğ, Ş).

---

## Sık gereken komutlar

| İş | Komut |
| --- | --- |
| Sunucuyu başlat | `python manage.py runserver` |
| Testleri çalıştır | `python manage.py test` |
| Yönetici parolası değiştir | `python manage.py changepassword <e-posta>` |
| Yeni yönetici ata | `/yonetim/` panelinden veya `python manage.py ilk_yonetici` |
| Veritabanı değişikliği | `python manage.py makemigrations && python manage.py migrate` |
| Üretim kontrolü | `python manage.py check --deploy` |

---

## Notlar

- `.env` dosyası `.gitignore`'da — GitHub'a gitmez. Yine de içinde düz metin
  parola tutmamanız önerilir; hesap oluşturulduktan sonra
  `SUPERADMIN_PASSWORD` satırını boşaltabilirsiniz.
- E-posta doğrulaması `DEBUG`'a bağlı **değildir**; tek belirleyici `.env`
  içindeki `EMAIL_VERIFICATION` satırıdır ve varsayılanı `none`. Bir dönem bu
  satırda "DEBUG=False olunca zorunlu hâle gelir" yazıyordu; kodda öyle bir bağ
  hiç olmadı. Üretime geçerken `EMAIL_VERIFICATION=mandatory` yazın ve **önce**
  çalışan bir SMTP kurun, yoksa hiç kimse kayıt olamaz. `none` bırakılırsa
  herkes sahibi olmadığı bir adresle kayıt olup anında giriş yapabilir.
  `python manage.py check --deploy` bu durumda `halisaha.W001` uyarısı verir.
