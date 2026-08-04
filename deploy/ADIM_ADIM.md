# Adım Adım Yayına Alma — hangi düğmeye basılacağı dahil

Bu belge `KURULUM.md`'nin tıklama düzeyinde ayrıntılı hâli. Oracle hesabınız
açıldıysa buradan devam edin.

**Önce okuyun:** Oracle konsolunun arayüzü zaman zaman değişiyor. Düğme
adları birebir tutmazsa panik yapmayın; her adımda **menü yolunu** ve
**aradığınız şeyi** de yazdım, isim biraz farklı olsa da yeri aynı kalıyor.

Toplam süre: yaklaşık 1-1,5 saat. En uzun bekleme DNS yayılması.

İşaretler:
- ⚠️ = burada durup kontrol edin, atlarsanız sonraki adımlar çalışmaz
- 💡 = işi kolaylaştıran bilgi

---

# BÖLÜM A — Kodu GitHub'a gönderin (5 dk)

Sunucu kodu GitHub'dan çekecek. `deploy/` klasörü GitHub'da yoksa hiçbir
şey çalışmaz.

Kendi bilgisayarınızda, proje klasöründe PowerShell açın:

```powershell
cd "c:\Users\hikme\Desktop\Halisaha Takip"
git status
```

⚠️ Çıktıda `.env` **görünmemeli**. Görünüyorsa durun ve bana yazın.

```powershell
git add -A
git commit -m "Yayına alma dosyaları"
git push
```

Tarayıcıda `github.com/ozankaya4/halisahatakip` adresini açın ve `deploy`
klasörünün göründüğünü doğrulayın.

---

# BÖLÜM B — Oracle'da sunucu oluşturma (20 dk)

## B1. Konsola girin

1. [cloud.oracle.com](https://cloud.oracle.com) adresine gidin
2. **Sign In** düğmesine basın
3. **Cloud Account Name** kutusuna hesap adınızı (tenancy) yazın →
   **Next**
4. Kullanıcı adı + parola → **Sign In**

Karşınıza konsolun ana sayfası gelir.

💡 Sağ üstte bölgenin **Germany Central (Frankfurt)** yazdığını kontrol
edin. Başka bir bölgedeyse oradan Frankfurt'a geçin.

## B2. Instance oluşturma ekranını açın

1. Sol üstteki **☰** (hamburger menü) simgesine basın
2. **Compute** başlığına tıklayın
3. Açılan listeden **Instances** seçin
4. Sayfanın solunda **Compartment** (bölme) seçici var; hesabınızın adıyla
   aynı olan kök bölme seçili olsun
5. Mavi **Create instance** düğmesine basın

## B3. İsim ve yerleşim

1. **Name** kutusuna: `halisaha`
2. **Create in compartment**: değiştirmeyin
3. **Placement** bölümü: **Availability domain** → `AD-1` kalsın

💡 İleride kapasite hatası alırsanız buraya dönüp AD-2 / AD-3 deneyeceğiz.

## B4. Görüntü (işletim sistemi) seçin

1. **Image and shape** bölümünü bulun
2. **Edit** düğmesine basın (bölüm kapalıysa önce açın)
3. **Change image** düğmesine basın
4. Açılan panelde **Canonical Ubuntu** satırını işaretleyin
5. **Image version** listesinden **24.04** seçin
6. Sağ altta **Select image** düğmesine basın

## B5. Şekil (donanım) seçin — en kritik adım

1. **Change shape** düğmesine basın
2. Üstteki sekmelerden **Ampere** sekmesine geçin
   (Intel/AMD değil — **Ampere** ARM işlemci)
3. Listeden **VM.Standard.A1.Flex** satırını işaretleyin
4. Aşağıda iki kaydırma çubuğu çıkar:
   - **Number of OCPUs**: `2`
   - **Amount of memory (GB)**: `12`
5. ⚠️ Satırın yanında **Always Free eligible** etiketini görün. Görünmüyorsa
   sayıları düşürün — bu etiket yoksa **ücret çıkar**.
6. **Select shape** düğmesine basın

> ### "Out of host capacity" hatası alırsanız
> Frankfurt'ta ARM kapasitesi sık tükeniyor. Sırayla deneyin:
> 1. B3'e dönüp **AD-2**, sonra **AD-3** seçin
> 2. Birkaç saat sonra tekrar deneyin (sabah erken saatler daha şanslı)
> 3. Olmuyorsa **Change shape** → **AMD** sekmesi →
>    **VM.Standard.E2.1.Micro** (1 GB RAM, her zaman müsait)
>
> AMD'yi seçerseniz **bana yazın**: 1 GB RAM'de PostgreSQL yerine SQLite
> kullanmak gerekir, kurulum betiğini ona göre değiştiririm.

## B6. Ağ ayarları

**Networking** bölümünde:

1. **Primary network**: `Create new virtual cloud network` seçili olsun
2. **New virtual cloud network name**: varsayılan isim kalsın
3. **Subnet**: `Create new public subnet` seçili olsun
4. ⚠️ **Assign a public IPv4 address** → **Yes** olmalı. Hayır olursa
   sunucuya dışarıdan hiç erişemezsiniz.

## B7. SSH anahtarı

Sunucuya parolayla değil, anahtarla bağlanacaksınız.

**Kendi bilgisayarınızda** yeni bir PowerShell penceresi açın:

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\oracle_halisaha" -C "halisaha"
```

- **Enter passphrase**: boş bırakıp Enter'a basabilirsiniz (ya da bir parola
  koyun; her bağlantıda sorar)
- İki dosya oluşur: `oracle_halisaha` (özel — **kimseyle paylaşmayın**) ve
  `oracle_halisaha.pub` (açık)

Açık anahtarı ekrana yazdırın:

```powershell
Get-Content "$env:USERPROFILE\.ssh\oracle_halisaha.pub"
```

Çıkan tek satırı (`ssh-ed25519 AAAA...` diye başlar) kopyalayın.

Oracle ekranında **Add SSH keys** bölümünde:

1. **Paste public keys** seçeneğini işaretleyin
2. Kutuya kopyaladığınız satırı yapıştırın

💡 Alternatif: **Generate a key pair for me** seçip **Save private key**
ile indirebilirsiniz. Ama anahtarı kendiniz üretmek daha güvenli, çünkü
özel anahtar bilgisayarınızdan hiç çıkmaz.

## B8. Disk

1. **Boot volume** bölümünü açın
2. **Specify a custom boot volume size** kutusunu işaretleyin
3. **Boot volume size (GB)**: `100`

💡 Always Free toplam 200 GB disk veriyor; 100 GB rahatça sınır içinde.

## B9. Oluşturun

1. Sayfanın altındaki mavi **Create** düğmesine basın
2. Durum önce turuncu **PROVISIONING**, 1-2 dakika sonra yeşil **RUNNING**
   olur
3. ⚠️ Sayfadaki **Public IP address** değerini bir yere not edin. Bundan
   sonra `<SUNUCU_IP>` yazan her yere bunu yazacaksınız.

---

# BÖLÜM C — Güvenlik kuralları (5 dk)

Bu bölüm atlanırsa site **hiç açılmaz** ve hata mesajı da almazsınız,
sadece sonsuza kadar yüklenir. Oracle'da en çok takılınan yer burası.

1. Sol üstte **☰** menü
2. **Networking** → **Virtual cloud networks**
3. Listede B6'da oluşan VCN'e tıklayın (adı `vcn-` ile başlar)
4. Sol alttaki **Resources** listesinden **Security Lists** seçin
5. **Default Security List for vcn-...** satırına tıklayın
6. Mavi **Add Ingress Rules** düğmesine basın

Açılan formda **birinci kural**:

| Alan | Değer |
|---|---|
| Stateless | işaretsiz bırakın |
| Source Type | `CIDR` |
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | `TCP` |
| Source Port Range | boş bırakın |
| Destination Port Range | `80` |

7. Formun altındaki **+ Another Ingress Rule** düğmesine basın
8. **İkinci kural**: aynısını doldurun, yalnızca
   **Destination Port Range** = `443`
9. Mavi **Add Ingress Rules** düğmesine basıp kaydedin

⚠️ Listede 80 ve 443 için iki yeni satır göründüğünü doğrulayın.

---

# BÖLÜM D — Namecheap DNS (5 dk + bekleme)

1. [namecheap.com](https://www.namecheap.com) → sağ üst **Sign In**
2. Sol menüden **Domain List**
3. `halisahadefteri.site` satırının sağındaki **MANAGE** düğmesine basın
4. Üstteki sekmelerden **Advanced DNS** sekmesine geçin

## D1. Hazır kayıtları silin

**HOST RECORDS** tablosunda Namecheap'in eklediği park sayfası kayıtları
var. Bunlar trafiği sunucunuz yerine reklam sayfasına götürür:

| Silinecek satır | Tip |
|---|---|
| `@` → `http://www.halisahadefteri.site/` | URL Redirect Record |
| `www` → `parkingpage.namecheap.com` | CNAME Record |

Her satırın en sağındaki **çöp kutusu** simgesine basarak ikisini de silin.

## D2. Kendi kayıtlarınızı ekleyin

**ADD NEW RECORD** düğmesine basın:

**Birinci kayıt:**
| Alan | Değer |
|---|---|
| Type | `A Record` |
| Host | `@` |
| Value | `<SUNUCU_IP>` |
| TTL | `Automatic` |

Satırın sağındaki **yeşil onay (✓)** işaretine basıp kaydedin.

**İkinci kayıt:** aynısı, yalnızca **Host** = `www`

Sayfanın üstünde yeşil **All changes saved** yazısını görün.

## D3. Yayılmayı bekleyin

Kendi bilgisayarınızda PowerShell:

```powershell
nslookup halisahadefteri.site
nslookup www.halisahadefteri.site
```

⚠️ **Buradan devam etmeden önce ikisinin de sunucunuzun IP'sini
yazdırdığını görün.** Namecheap genelde 5-30 dakikada yayılır.

Neden önemli: DNS hazır değilken sertifika adımını (Bölüm G) çalıştırırsanız
Let's Encrypt başarısız denemeleri sayar ve **saatlerce yeni deneme
yaptırmaz**. Beklemek, beklememekten hızlıdır.

---

# BÖLÜM E — Sunucuya bağlanın (5 dk)

Kendi bilgisayarınızda PowerShell:

```powershell
ssh -i "$env:USERPROFILE\.ssh\oracle_halisaha" ubuntu@<SUNUCU_IP>
```

İlk bağlantıda `Are you sure you want to continue connecting?` sorusuna
`yes` yazıp Enter.

Komut satırı `ubuntu@halisaha:~$` şekline dönerse bağlandınız.

> ### "UNPROTECTED PRIVATE KEY FILE" hatası
> Windows'ta anahtar dosyasının izinleri fazla açıksa çıkar. Düzeltmek için:
> ```powershell
> icacls "$env:USERPROFILE\.ssh\oracle_halisaha" /inheritance:r
> icacls "$env:USERPROFILE\.ssh\oracle_halisaha" /grant:r "${env:USERNAME}:(R)"
> ```
> Sonra ssh komutunu tekrar deneyin.

> ### "Connection timed out" hatası
> Bölüm C yapılmamış demektir. Security List kurallarına geri dönün.

---

# BÖLÜM F — Kurulum (25 dk)

Buradan sonrası **sunucudaki** terminalde.

## F1. Kodu indirin

```bash
sudo mkdir -p /srv/halisaha
sudo chown ubuntu:ubuntu /srv/halisaha
git clone https://github.com/ozankaya4/halisahatakip.git /srv/halisaha
cd /srv/halisaha
```

## F2. Sunucu ayarları

```bash
cp deploy/sunucu.env.ornek deploy/sunucu.env
openssl rand -base64 32
```

Çıkan rastgele metni kopyalayın, sonra:

```bash
nano deploy/sunucu.env
```

`DB_PAROLA=` satırının sonuna kopyaladığınız metni yapıştırın
(sağ tıklama = yapıştır). `ALAN_ADI` zaten doğru.

Kaydetmek için: **Ctrl+O** → **Enter** → **Ctrl+X**

## F3. Gmail uygulama parolası alın

⚠️ Bu adım zorunlu. Olmadan **hiç kimse kayıt olamaz**, siz dahil.

Kendi bilgisayarınızda tarayıcıda:

1. [myaccount.google.com/security](https://myaccount.google.com/security)
   → **2 Adımlı Doğrulama** açık olmalı (kapalıysa önce açın)
2. [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   adresine gidin
3. **App name** kutusuna `Halisaha` yazın → **Create**
4. Ekranda 16 harflik bir parola çıkar (`abcd efgh ijkl mnop` gibi)
5. **Boşlukları silerek** kopyalayın: `abcdefghijklmnop`

Bu pencereyi kapatmadan bir sonraki adıma geçin; parola bir daha
gösterilmez.

## F4. Uygulama ayarları

Sunucuda:

```bash
cd /srv/halisaha
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Çıkan uzun metni kopyalayın, sonra:

```bash
nano .env
```

Şu satırları bulup değiştirin (nano'da yön tuşlarıyla gezinin):

```ini
SECRET_KEY=<kopyaladığınız uzun metin>
DEBUG=False
ALLOWED_HOSTS=halisahadefteri.site,www.halisahadefteri.site
CSRF_TRUSTED_ORIGINS=https://halisahadefteri.site,https://www.halisahadefteri.site

DATABASE_URL=postgres://halisaha:<F2'deki DB_PAROLA>@localhost:5432/halisaha

USE_X_ACCEL_REDIRECT=True
BEHIND_PROXY=True
SECURE_SSL_REDIRECT=False

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=hikmetozankaya@gmail.com
EMAIL_HOST_PASSWORD=<F3'teki 16 harflik parola, boşluksuz>
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=Halısaha Defteri <hikmetozankaya@gmail.com>

SUPERADMIN_EMAIL=hikmetozankaya@gmail.com
SUPERADMIN_PASSWORD=<YENİ ve güçlü bir parola>
SUPERADMIN_NAME=Ozan Kaya
```

⚠️ `SECURE_SSL_REDIRECT` şimdilik **False** kalsın. Sertifikanız henüz yok;
şimdi True yaparsanız kendi sitenize giremezsiniz.

⚠️ `SUPERADMIN_PASSWORD` için **yeni** bir parola seçin. Bana yazdığınız
eskisini kullanmayın.

Kaydedin: **Ctrl+O** → **Enter** → **Ctrl+X**

## F5. Kurulum betiğini çalıştırın

```bash
sudo bash /srv/halisaha/deploy/kurulum.sh
```

5-10 dakika sürer. Yeşil `==>` satırları ilerlemeyi gösterir. Sonunda
"Kurulum bitti" yazan bir özet çıkar.

⚠️ Kontrol:

```bash
curl -I http://halisahadefteri.site
```

`HTTP/1.1 200` ya da `301/302` görmelisiniz. `Connection refused` veya
takılma olursa Bölüm C'ye dönün.

---

# BÖLÜM G — HTTPS, Google, ilk yönetici (15 dk)

## G1. Sertifika

```bash
sudo certbot --nginx -d halisahadefteri.site -d www.halisahadefteri.site
```

Sorular:
- **E-posta adresi**: `hikmetozankaya@gmail.com`
- **Şartları kabul (A/Y)**: `Y`
- **Duyuru listesi (Y/N)**: `N`

Sonunda "Congratulations!" görürsünüz.

## G2. HTTPS zorunlu yapın

```bash
nano /srv/halisaha/.env
```

`SECURE_SSL_REDIRECT=False` satırını `True` yapın →
**Ctrl+O** → **Enter** → **Ctrl+X**

```bash
sudo systemctl restart halisaha
```

Tarayıcıda `https://halisahadefteri.site` açın. Kilit simgesi görünmeli.

## G3. Google ile giriş

Kendi bilgisayarınızda tarayıcıda:

1. [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials)
2. **OAuth 2.0 Client IDs** listesinden istemcinize tıklayın
3. **Authorized JavaScript origins** → **+ ADD URI**:
   ```
   https://halisahadefteri.site
   https://www.halisahadefteri.site
   ```
4. **Authorized redirect URIs** → **+ ADD URI**:
   ```
   https://halisahadefteri.site/hesap/google/login/callback/
   https://www.halisahadefteri.site/hesap/google/login/callback/
   ```
5. **SAVE** düğmesine basın

⚠️ Localhost adreslerini **silmeyin**; yerelde geliştirmeye devam
edeceksiniz.

💡 Sondaki `/` işareti dahil birebir aynı olmalı. Eksikse Google
`redirect_uri_mismatch` hatası verir.

💡 Google değişikliklerin yayılması birkaç dakika sürebilir.

## G4. İlk yöneticiyi oluşturun

Sunucuda:

```bash
cd /srv/halisaha
sudo -u halisaha .venv/bin/python manage.py ilk_yonetici
```

Sonra parolayı ayar dosyasından silin:

```bash
nano /srv/halisaha/.env
```

`SUPERADMIN_PASSWORD=...` satırının içeriğini boşaltın →
**Ctrl+O** → **Enter** → **Ctrl+X**

---

# BÖLÜM H — Çalıştığını doğrulayın

Tarayıcıda `https://halisahadefteri.site` açıp sırayla deneyin:

- [ ] Ana sayfa açılıyor, yazı tipleri ve renkler doğru
- [ ] Karanlık/aydınlık tema düğmesi çalışıyor
- [ ] Oluşturduğunuz yönetici hesabıyla giriş yapabiliyorsunuz
- [ ] **Google ile giriş** çalışıyor
- [ ] Yeni bir hesapla kayıt olunca **doğrulama e-postası geliyor**
      (gelmediyse spam klasörüne bakın)
- [ ] Grup oluşturabiliyorsunuz
- [ ] Maç ekleyip **fotoğraf yükleyebiliyorsunuz** ve fotoğraf görünüyor
- [ ] Sohbet şifreleme parolası kurulabiliyor
- [ ] İki farklı tarayıcıda sohbet açıp mesaj yazınca 6 saniye içinde
      diğerinde görünüyor

Hepsi tamamsa yayındasınız.

---

# Günlük kullanım

```bash
# Yeni sürüm yayına al
sudo bash /srv/halisaha/deploy/guncelle.sh

# Çalışıyor mu
sudo systemctl status halisaha

# Canlı günlük (Ctrl+C ile çıkın)
sudo journalctl -u halisaha -f

# Elle yedek
sudo /usr/local/bin/halisaha-yedek
```

Yedekleri ayda bir kendi bilgisayarınıza indirin:

```powershell
scp -i "$env:USERPROFILE\.ssh\oracle_halisaha" -r ubuntu@<SUNUCU_IP>:/var/backups/halisaha "$env:USERPROFILE\Desktop\halisaha-yedek"
```

---

# Bir şey ters giderse

| Belirti | Bakılacak yer |
|---|---|
| Site hiç açılmıyor, sonsuz yükleniyor | Bölüm C (Security List) |
| `Connection timed out` (ssh) | Bölüm C |
| Namecheap park sayfası çıkıyor | Bölüm D1, kayıtlar silinmemiş |
| `502 Bad Gateway` | `sudo journalctl -u halisaha -n 50` |
| Kayıt e-postası gelmiyor | F3'teki parola, `.env` içinde boşluk var mı |
| Google `redirect_uri_mismatch` | G3, adresler birebir mi (sondaki `/`) |
| Fotoğraflar görünmüyor | `.env` içinde `USE_X_ACCEL_REDIRECT=True` mi |
| certbot başarısız | DNS yayılmamış — Bölüm D3'e dönün, bekleyin |
| Sertifika "too many requests" | Let's Encrypt sınırı; 1 saat bekleyin |

Takılırsanız hata mesajının **tamamını** bana yapıştırın.
