# Yayına Alma — Oracle Cloud (Always Free), Frankfurt

Aylık maliyet: **yalnızca alan adı.** Sunucu, veritabanı, TLS sertifikası ve
trafik ücretsiz.

Bu belge Ubuntu 24.04 (ARM / Ampere A1) varsayar.

---

## Önce okuyun: iki şey kurulumu kilitler

Sırayla ilerlerseniz ikisine de takılmazsınız, ama sebebini bilmek iyi:

1. **Oracle'da güvenlik duvarı iki katmanlı.** Konsoldaki Security List'te
   80/443 portlarını açsanız bile, makinenin kendi `iptables` kuralları
   isteği düşürür. "DNS doğru, nginx çalışıyor, ama site açılmıyor"
   şikâyetlerinin neredeyse tamamı budur. `kurulum.sh` sunucu tarafını
   hallediyor; konsol tarafını **siz** yapacaksınız (adım 2).

2. **Üretimde e-posta doğrulaması zorunlu.** `settings.py` içinde
   `ACCOUNT_EMAIL_VERIFICATION = "mandatory" if not DEBUG` yazıyor. Yani
   `DEBUG=False` olduğu anda, çalışan bir SMTP olmadan **hiç kimse kayıt
   olamaz** — doğrulama e-postası gitmez, hesap açılmaz. Ücretsiz çözüm
   adım 6'da.

---

## 1. Sunucuyu oluşturun

[cloud.oracle.com](https://cloud.oracle.com) → hesap açın. Kayıt sırasında
kart isteniyor (doğrulama için); Always Free sınırları içinde kalırsanız
ücret çıkmaz.

**Bölge seçimi kalıcıdır ve sonradan değiştirilemez.** `Germany Central
(Frankfurt)` seçin — Türkiye'den ~40 ms, ABD bölgelerinde ~150 ms olurdu.

Compute → Instances → Create Instance:

| Alan | Değer |
|---|---|
| Image | Canonical Ubuntu 24.04 |
| Shape | `VM.Standard.A1.Flex` (Ampere ARM) |
| OCPU / RAM | 2 OCPU / 12 GB |
| Boot volume | 100 GB |
| SSH key | Kendi açık anahtarınızı yükleyin |

> **"Out of capacity" hatası alırsanız:** Frankfurt'ta ARM kapasitesi sık
> sık tükeniyor. Seçenekler: birkaç saat sonra tekrar deneyin, Amsterdam'ı
> deneyin, ya da shape'i `VM.Standard.E2.1.Micro` (AMD, 1 GB RAM) yapın —
> bu her zaman müsait. AMD ile de çalışır; sadece PostgreSQL yerine SQLite
> kullanmanız daha rahat olur (bkz. adım 9).

> **Oracle 15 Haziran 2026'da Always Free ARM kotasını duyurmadan 4 OCPU /
> 24 GB'dan 2 OCPU / 12 GB'a düşürdü.** Bu uygulama için hâlâ fazlasıyla
> yeterli, ama ileride tekrar düşerse şaşırmayın.

## 2. Security List (bunu atlamayın)

Networking → Virtual Cloud Networks → VCN'iniz → Security Lists →
Default Security List → **Add Ingress Rules**:

| Source CIDR | IP Protocol | Destination Port |
|---|---|---|
| `0.0.0.0/0` | TCP | 80 |
| `0.0.0.0/0` | TCP | 443 |

## 3. Alan adını yönlendirin (Namecheap)

Namecheap → **Domain List** → `halisahadefteri.site` yanındaki **Manage**
→ **Advanced DNS** sekmesi.

### Önce hazır kayıtları silin

Namecheap yeni alan adlarına otomatik olarak park sayfası kaydı ekler.
Bunlar sunucunuza giden trafiği çalar; **silmezseniz site açılmaz**:

| Silinecek | Tipi |
|---|---|
| `@` → `http://www.halisahadefteri.site/` | URL Redirect Record |
| `www` → `parkingpage.namecheap.com` | CNAME Record |

Sağdaki çöp kutusu simgesiyle ikisini de silin.

### Sonra kendi kayıtlarınızı ekleyin

**Add New Record** ile iki adet **A Record**:

| Type | Host | Value | TTL |
|---|---|---|---|
| A Record | `@` | `<SUNUCU_IP>` | Automatic |
| A Record | `www` | `<SUNUCU_IP>` | Automatic |

`<SUNUCU_IP>` = Oracle konsolundaki **Public IP** adresi.

> Nameserver ayarı **Namecheap BasicDNS** kalsın; değiştirmenize gerek yok.

### Yayılmayı bekleyin

```bash
dig +short halisahadefteri.site
dig +short www.halisahadefteri.site
```

İkisi de sunucunuzun IP'sini yazdırmalı. Namecheap genelde 5-30 dakikada
yayılır. **Sertifika adımına (adım 8) geçmeden önce bu çıktıyı mutlaka
görün** — DNS hazır değilken certbot başarısız olur ve Let's Encrypt
tekrar denemelerinizi bir süreliğine sınırlar.

## 4. Kodu sunucuya alın

```bash
ssh ubuntu@<SUNUCU_IP>

sudo mkdir -p /srv/halisaha
sudo chown ubuntu:ubuntu /srv/halisaha
git clone https://github.com/ozankaya4/halisahatakip.git /srv/halisaha
cd /srv/halisaha
```

## 5. Kurulum ayarları

```bash
cp deploy/sunucu.env.ornek deploy/sunucu.env
openssl rand -base64 32          # çıktıyı DB_PAROLA'ya yapıştırın
nano deploy/sunucu.env
```

## 6. Uygulama ayarları (`.env`)

```bash
cp .env.example .env
# Sanal ortam henüz yok (adım 7'de kurulacak), bu yüzden sistem
# python'u ile üretiyoruz.
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
nano .env
```

Üretim için değiştirilecekler:

```ini
SECRET_KEY=<yukarıda üretilen>
DEBUG=False
ALLOWED_HOSTS=halisahadefteri.site,www.halisahadefteri.site
CSRF_TRUSTED_ORIGINS=https://halisahadefteri.site,https://www.halisahadefteri.site

DATABASE_URL=postgres://halisaha:<DB_PAROLA>@localhost:5432/halisaha

# nginx korumalı dosyaları devralsın
USE_X_ACCEL_REDIRECT=True
BEHIND_PROXY=True

# Sertifika alındıktan SONRA True yapın (adım 8)
SECURE_SSL_REDIRECT=False
```

### E-posta (zorunlu — bu olmadan kimse kayıt olamaz)

Ücretsiz ve bu ölçek için fazlasıyla yeterli yol: **Gmail uygulama
parolası**. Günde 500 e-posta sınırı var; 12 kişilik bir grup için bunun
yanına bile yaklaşmazsınız.

1. Google hesabınızda **iki adımlı doğrulama açık olmalı**
2. [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   → yeni uygulama parolası üretin (16 karakter)
3. `.env` içine:

```ini
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=hikmetozankaya@gmail.com
EMAIL_HOST_PASSWORD=<16 karakterlik uygulama parolası, boşluksuz>
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=Halısaha Takip <hikmetozankaya@gmail.com>
```

> Bu, normal Gmail parolanız **değildir**. Uygulama parolası yalnızca SMTP
> için geçerlidir ve istediğiniz zaman iptal edebilirsiniz.

### İlk yönetici

```ini
SUPERADMIN_EMAIL=hikmetozankaya@gmail.com
SUPERADMIN_PASSWORD=<güçlü, yeni bir parola>
SUPERADMIN_NAME=Ozan Kaya
```

> Sohbette paylaştığınız eski parolayı kullanmayın. Yöneticiyi
> oluşturduktan sonra bu üç satırı `.env`'den silin.

## 7. Kurulumu çalıştırın

```bash
sudo bash /srv/halisaha/deploy/kurulum.sh
```

Betik şunları yapar: paketler, iptables kuralları, `halisaha` sistem
kullanıcısı, PostgreSQL rolü + veritabanı, sanal ortam, göçler,
`collectstatic`, systemd servisi, nginx, günlük yedek görevi, otomatik
güvenlik güncellemeleri.

## 8. HTTPS

DNS yayıldıktan **sonra**:

```bash
sudo certbot --nginx -d halisahadefteri.site -d www.halisahadefteri.site
```

Sonra `.env` içinde `SECURE_SSL_REDIRECT=True` yapın ve yeniden başlatın:

```bash
sudo systemctl restart halisaha
```

Bu, HSTS'i ve `upgrade-insecure-requests` CSP direktifini de açar.
Sertifika otomatik yenilenir (`certbot.timer`).

## 9. Google ile giriş

[Google Cloud Console](https://console.cloud.google.com/apis/credentials) →
OAuth 2.0 Client ID'niz → **Authorized redirect URIs**'e ekleyin:

```
https://halisahadefteri.site/hesap/google/login/callback/
https://www.halisahadefteri.site/hesap/google/login/callback/
```

**Authorized JavaScript origins**:

```
https://halisahadefteri.site
https://www.halisahadefteri.site
```

Localhost adreslerini silmeyin; geliştirmeye devam edeceksiniz.

## 10. Nihai yöneticiyi oluşturun

```bash
cd /srv/halisaha
sudo -u halisaha .venv/bin/python manage.py ilk_yonetici
```

Ardından `.env`'den `SUPERADMIN_PASSWORD` satırını silin.

---

## Günlük kullanım

```bash
# Yeni sürümü yayına al (göç öncesi otomatik yedek alır)
sudo bash /srv/halisaha/deploy/guncelle.sh

# Durum ve günlükler
sudo systemctl status halisaha
sudo journalctl -u halisaha -f

# Elle yedek
sudo /usr/local/bin/halisaha-yedek
```

Yedekler `/var/backups/halisaha` altında, 14 gün saklanır. **Ayda bir
kendi bilgisayarınıza da indirin** — sunucu kaybolursa yedek de kaybolur:

```bash
scp -r ubuntu@<SUNUCU_IP>:/var/backups/halisaha ./yedekler/
```

## Boşta kalma toplaması (bu kurulumda geçerli değil)

Oracle, **Always Free** hesaplardaki makineleri 7 gün boyunca %10'un
altında CPU *ve* ağ kullanımı görürse durdurabiliyor.

**Bu kurulumda böyle bir risk yok**, çünkü hesap Pay-As-You-Go'ya
yükseltildi (bkz. `ADIM_ADIM.md`, Bölüm A2). PAYG hesaplarına boşta kalma
toplaması uygulanmıyor.

Yükseltmenin asıl sebebi ARM kapasitesiydi: Always Free hesapları donanım
sırasında en sona konduğu için sunucu bir türlü oluşturulamıyordu. Boşta
kalma riskinin ortadan kalkması ikinci bir kazanç oldu.

⚠️ Hesap artık faturalandırılabilir durumda. Always Free sınırları içinde
kaldığı sürece tutar 0 € kalır; güvence için 1 €'luk bütçe uyarısı
kurulmuş olmalı (ADIM_ADIM.md, A2.2). Harcamayı ara sıra kontrol edin:
**Billing & Cost Management → Cost Analysis**.

> İleride Always Free'ye geri dönerseniz yukarıdaki boşta kalma kuralı
> tekrar geçerli olur; bu bölüm o yüzden silinmedi.

## Sorun giderme

| Belirti | Bakılacak yer |
|---|---|
| Site hiç açılmıyor | Security List (adım 2) **ve** `sudo iptables -L INPUT -n` |
| Namecheap park sayfası çıkıyor | Adım 3'teki URL Redirect / CNAME kayıtları silinmemiş |
| `dig` yanlış IP veriyor | DNS henüz yayılmamış ya da A kaydı yanlış |
| 502 Bad Gateway | `sudo journalctl -u halisaha -n 50` — uygulama çökmüş |
| Kayıt olurken e-posta gelmiyor | Gmail uygulama parolası, `EMAIL_BACKEND` smtp mi |
| Google girişi `redirect_uri_mismatch` | Adım 9'daki adresler birebir aynı mı (sondaki `/` dahil) |
| Fotoğraflar 404 | `.env` içinde `USE_X_ACCEL_REDIRECT=True` ve nginx `/korumali-medya/` bloğu |
| Statik dosyalar gelmiyor | `sudo -u halisaha .venv/bin/python manage.py collectstatic` |
| CSRF hatası | `CSRF_TRUSTED_ORIGINS` şema (`https://`) ile yazılmış mı |
