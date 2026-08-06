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

# BÖLÜM A2 — Pay-As-You-Go'ya geçin (0 €, kapasite sorununu çözer)

## Neden

Always Free hesapları ARM donanımı dağıtılırken **en sona** konuyor. Bu
yüzden sunucu oluştururken üç kullanılabilirlik alanında da
"Out of host capacity / kapasite yok" hatası alınıyor. Sorun sizin
yapılandırmanızda değil, sıradaki yerinizde.

Oracle'ın bu duruma önerdiği çözüm hesabı **Pay-As-You-Go**'ya
yükseltmek. Adı yanıltıcı: bu ücretli bir plana geçmek **değil**.

| | Always Free | Pay-As-You-Go |
|---|---|---|
| Always Free kaynaklarının ücreti | 0 € | **0 €** (aynen devam eder) |
| Donanım sırasındaki yeriniz | en son | **öncelikli** |
| 7 gün boşta kalınca durdurulma | var | **yok** |
| Sınırı aşarsanız | oluşturulmaz | ücretlendirilir |

Yani sınırların içinde kaldığınız sürece fatura **0 €** olmaya devam
eder; değişen tek şey donanım kuyruğundaki önceliğiniz.

💡 PAYG hesaplarının eski **4 OCPU / 24 GB** kotasını koruduğuna dair
raporlar var (Always Free 15 Haziran 2026'da 2/12'ye düşürülmüştü).
Yükseltmeden sonra denemeye değer, bkz. B0.4.

## A2.1. Yükseltin

1. Oracle konsolunda **sağ üstteki profil simgesine** tıklayın
2. Açılan menüden **Upgrade to Pay As You Go** seçin
   (görünmüyorsa: ☰ → **Billing & Cost Management** → **Upgrade and
   Payment** → **Upgrade** düğmesi)
3. Kart bilgilerinizi girin ve onaylayın

Yükseltme genelde birkaç dakikada etkinleşir, bazen 1 saati bulur.

## A2.2. Bütçe uyarısı kurun — bu adımı atlamayın

Hesap artık faturalandırılabilir durumda. İlk kuruş harcandığında haber
almak için:

1. ☰ menü → **Billing & Cost Management**
2. **Budgets** → **Create Budget**
3. Doldurun:

| Alan | Değer |
|---|---|
| Name | `sifir-harcama-uyarisi` |
| Target Compartment | `hikmetozankaya (root)` |
| Monthly Budget Amount | `1` |
| Alert Rule: Threshold | `100` |
| Threshold Metric | `Actual Spend` (gerçekleşen harcama) |
| Email Recipients | `hikmetozankaya@gmail.com` |

4. **Create**

⚠️ Bu, "1 €'yu geçersem bana yaz" demek. Betiklerimiz Always Free
dışına çıkan hiçbir kaynak oluşturmuyor, dolayısıyla bu e-postanın hiç
gelmemesi gerekir. Gelirse bir şeyin ters gittiğini hemen anlarsınız.

## A2.3. Sonra ne olacak

Yükseltme etkinleştikten sonra doğrudan B0'a dönüp sunucuyu oluşturun.
Daha önce kapasite hatası veren komut artık geçmeli.

---

# BÖLÜM B0 — KOLAY YOL: Cloud Shell (önerilen)

Aşağıdaki B ve C bölümleri konsolda tıklayarak ilerliyor. Oracle arayüzü
sık değiştiği için bu yol yorucu olabiliyor.

**Cloud Shell**, Oracle konsolunun içine gömülü bir komut satırı. Zaten
sizin hesabınızla açılmış geliyor; komut yazıyorsunuz, iş oluyor. Komutlar
arayüz gibi değişmediği için çok daha güvenilir.

Bu yolu seçerseniz **B2-B9 ve tüm C bölümünü atlayabilirsiniz.**

## B0.1. Cloud Shell'i açın

1. Oracle konsolunda, sayfanın **sağ üst köşesindeki** simge sırasına bakın
2. **`>_`** şeklinde bir terminal simgesi var, ona tıklayın
   (bulamazsanız: `{;}` "Developer tools" simgesine tıklayın, açılan
   listeden **Cloud Shell** seçin)
3. Sayfanın altında siyah bir pencere açılır. İlk açılışta 30 saniye
   kadar "starting" yazabilir, bekleyin.
4. Sonunda şuna benzer bir satır görürsünüz:

```
hikmetozankaya@cloudshell:~ (eu-frankfurt-1)$
```

Bu satıra **komut istemi** deniyor. Buraya komut yazıp Enter'a basacaksınız.

## B0.2. Komutları nasıl yapıştıracaksınız

Uzun komutları elle yazmayın; kopyala-yapıştır yapın.

- **Kopyalama** (bu belgeden / sohbetten): metni fareyle seçip **Ctrl+C**
- **Cloud Shell'e yapıştırma**: pencereye tıklayın, sonra **sağ tık** →
  **Paste**

💡 Cloud Shell'de **Ctrl+V çalışmaz**. Terminal pencerelerinde Ctrl+V'nin
başka bir anlamı var. Sağ tık kullanın, ya da **Ctrl+Shift+V** deneyin.

⚠️ Her komuttan sonra **Enter** tuşuna basmayı unutmayın. Enter'a basmadan
komut çalışmaz.

## B0.3. Kodu Cloud Shell'e indirin

Aşağıdaki üç satırı **tek tek** yapıştırıp her birinden sonra Enter'a basın:

```bash
git clone https://github.com/ozankaya4/halisahatakip.git
```

```bash
cd halisahatakip/deploy
```

```bash
ls
```

Son komut dosyaları listeler. `cloudshell_sunucu_olustur.sh` adını
görüyorsanız her şey yolunda.

## B0.4. Sunucuyu oluşturun

```bash
bash cloudshell_sunucu_olustur.sh
```

Betik sırayla şunları yapar ve her adımı ekrana yazar:

1. **SSH anahtarı sorar.** Anahtarınız yoksa "Anahtar şimdi oluşturulsun
   mu?" diye sorar → `evet` yazıp Enter. Kendi bilgisayarınızda hiçbir şey
   yapmanız gerekmez.
2. Ağınızı, Ubuntu görüntüsünü ve bölgeleri bulur
3. Ne oluşturacağını özetler → `evet` yazıp Enter
4. Kapasite bulana kadar tüm bölgeleri dener
5. Sonunda **sunucunun genel IP adresini** yazar

⚠️ Bu IP adresini bir yere not edin.

> **"Genel alt ağ bulunamadı" hatası alırsanız:** ağınız henüz yok
> demektir. B6a bölümündeki VCN Wizard adımını yapın (6 tıklama), sonra
> bu komutu tekrar çalıştırın.

> ### "Kapasite yok" hatası alırsanız
>
> **1. Önce PAYG'ye geçin.** Sebebin neredeyse tamamı bu: Always Free
> hesapları ARM sırasında en sonda. Bkz. **BÖLÜM A2**. Ücretsiz ve
> kalıcı çözüm budur.
>
> **2. PAYG'den sonra hâlâ olmuyorsa** daha küçük bir makine isteyin;
> küçük parçalar çok daha kolay bulunuyor:
> ```bash
> OCPU=1 BELLEK_GB=6 bash cloudshell_sunucu_olustur.sh
> ```
>
> **3. Israrla deneyin.** Kapasite gün içinde açılıp kapanıyor:
> ```bash
> TEKRAR=50 BEKLEME=300 OCPU=1 BELLEK_GB=6 bash cloudshell_sunucu_olustur.sh
> ```
> 5 dakikada bir, ~4 saat dener. Cloud Shell oturumu kapanırsa komut da
> durur; sekmeyi açık tutun. Ctrl+C ile durdurulur.
>
> 💡 PAYG'ye geçtiyseniz büyük makineyi de deneyebilirsiniz:
> ```bash
> OCPU=4 BELLEK_GB=24 bash cloudshell_sunucu_olustur.sh
> ```
> Kapasite hatası verirse varsayılan 2/12'ye dönmek yeterli.

## B0.5. Güvenlik kurallarını açın

```bash
bash cloudshell_guvenlik_kurallari.sh
```

Mevcut kuralları gösterir, ne değişeceğini yazar, `evet` ister.

Sonunda listede **22, 80 ve 443** görüyorsanız tamam.

## B0.6. Sunucuya bağlanın

```bash
ssh -i ~/halisaha_anahtar ubuntu@<SUNUCU_IP>
```

`<SUNUCU_IP>` yerine B0.4'te not ettiğiniz adresi yazın (köşeli
parantezler olmadan).

İlk bağlantıda şu soru çıkar:

```
Are you sure you want to continue connecting (yes/no)?
```

`yes` yazıp Enter'a basın. (`y` değil, tam olarak `yes`.)

Komut istemi şuna dönerse bağlandınız:

```
ubuntu@halisaha:~$
```

✅ Artık **BÖLÜM F**'ye geçebilirsiniz. B'nin geri kalanını ve C'yi
atlayın.

💡 Bundan sonra sunucuya hep Cloud Shell'den bağlanabilirsiniz; kendi
bilgisayarınıza bir şey kurmanız gerekmiyor.

---

# BÖLÜM B — Oracle'da sunucu oluşturma (20 dk)

> Bu bölüm **tıklayarak** ilerleyen yol. B0'daki Cloud Shell yolunu
> kullandıysanız buradan **F bölümüne atlayın**.

## B1. Konsola girin

1. [cloud.oracle.com](https://cloud.oracle.com) adresine gidin
2. **Sign In** düğmesine basın
3. **Cloud Account Name** kutusuna hesap adınızı (tenancy) yazın →
   **Next**
4. Kullanıcı adı + parola → **Sign In**

Karşınıza konsolun ana sayfası gelir.

💡 Sağ üstte bölgenin **Germany Central (Frankfurt)** yazdığını kontrol
edin. Başka bir bölgedeyse oradan Frankfurt'a geçin veya yeni hesap olusturun.

## B2. Instance oluşturma ekranını açın

1. Sol üstteki **☰** (hamburger menü) simgesine basın
2. **Compute** başlığına tıklayın
3. Açılan listeden **Instances** seçin
4. Sayfanın solunda **Compartment** (bölme) seçici var; hesabınızın adıyla
   aynı olan kök bölme seçili olsun
5. **Create instance** düğmesine basın

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
>
> **Asıl çözüm: BÖLÜM A2'deki Pay-As-You-Go yükseltmesi.** Always Free
> hesapları ARM donanımı sırasında en sona konuyor; hata bundan
> kaynaklanıyor. Yükseltme ücretsiz ve kalıcı çözüm.
>
> Yükseltmeden sonra hâlâ olmuyorsa sırayla:
> 1. B3'e dönüp **AD-2**, sonra **AD-3** seçin
> 2. B5'te OCPU/bellek değerlerini düşürün (1 OCPU / 6 GB çok daha
>    kolay bulunuyor)
> 3. Birkaç saat sonra tekrar deneyin (sabah erken saatler daha şanslı)
> 4. Son çare **Change shape** → **AMD** sekmesi →
>    **VM.Standard.E2.1.Micro** (1 GB RAM, her zaman müsait)
>
> AMD'yi seçerseniz Claude'a haber verin: 1 GB RAM'de PostgreSQL yerine
> SQLite kullanmak, takas alanı eklemek ve Argon2 parola karma
> ayarlarını hafifletmek gerekiyor (yoksa girişler yavaşlar).

## B6. Ağ ayarları

⚠️ **Ağı instance ekranından oluşturmayın.** Instance oluşturma sayfasının
içindeki "Create new public subnet" seçeneği kullanıldığında
**Automatically assign public IPv4 address** anahtarı kapalı ve
tıklanamaz kalıyor; altında da şu uyarı çıkıyor:

> You must select a public subnet to assign a public IPv4 address.

Sebep: alt ağ (subnet) henüz oluşmadığı için konsol onun "public"
olduğunu doğrulayamıyor. Oracle'ın kendi uyarısı da ağı önce ayrı
oluşturmanızı söylüyor.

Çözüm: ağı **VCN Wizard** ile önceden kurup instance ekranında hazır ağı
seçmek. Bu yol daha sağlam, çünkü sihirbaz Internet Gateway ve yönlendirme
kurallarını da doğru kuruyor.

### B6a. Önce ağı oluşturun (VCN Wizard)

💡 Instance formundaki bilgileri kaybetmemek için **yeni bir tarayıcı
sekmesi** açın. (Kaybolursa da sorun değil, B3-B5 iki dakika sürüyor.)

1. Yeni sekmede [cloud.oracle.com](https://cloud.oracle.com) konsolu
2. Sol üstte **☰** menü → **Networking** → **Virtual cloud networks**
3. Soldaki **Compartment** seçici `hikmetozankaya (root)` olsun
4. Mavi **Start VCN Wizard** düğmesine basın
5. Açılan pencerede **Create VCN with Internet Connectivity** seçeneğini
   işaretleyin
6. Sağ altta **Start VCN Wizard** düğmesine basın

Sihirbazın 1. adımında:

| Alan | Değer |
|---|---|
| VCN Name | `halisaha-vcn` |
| Compartment | `hikmetozankaya (root)` |
| VCN CIDR Block | `10.0.0.0/16` (varsayılan) |
| Public Subnet CIDR Block | `10.0.0.0/24` (varsayılan) |
| Private Subnet CIDR Block | `10.0.1.0/24` (varsayılan) |

7. **Next** düğmesine basın
8. Özet ekranını gözden geçirip **Create** düğmesine basın
9. Sihirbaz sırayla VCN, iki alt ağ, Internet Gateway, NAT Gateway,
   Service Gateway, yönlendirme tabloları ve güvenlik listelerini oluşturur
10. Hepsi yeşil tik alınca **View VCN** düğmesine basın

⚠️ Kaynak listesinde **Public Subnet-halisaha-vcn** adında bir alt ağ
gördüğünüzü doğrulayın. Bir sonraki adımda bunu seçeceksiniz.

### B6b. Instance ekranında hazır ağı seçin

Instance oluşturma sekmesine dönün. (Sekmeyi kapattıysanız B2-B5'i
tekrarlayın.) **Networking** bölümünde:

1. **Primary network**: `Select existing virtual cloud network` seçeneğini
   işaretleyin
2. Altındaki listeden **halisaha-vcn** seçin
3. **Subnet**: `Select existing subnet` seçeneğini işaretleyin
4. Listeden **Public Subnet-halisaha-vcn** seçin
   (⚠️ *Private* olanı değil)
5. ✅ **Automatically assign public IPv4 address** anahtarı artık
   tıklanabilir hâle geldi. **Açık konuma getirin.**

💡 VCN listede görünmüyorsa sayfayı yenileyin (F5) ve bölümü tekrar açın.

⚠️ Bu anahtar açılmazsa sunucuya dışarıdan hiç erişemezsiniz; ne SSH ne
web. Devam etmeden önce açık olduğundan emin olun.

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
3. Listeden **halisaha-vcn** üzerine tıklayın
4. Sol alttaki **Resources** listesinden **Subnets** seçin
5. **Public Subnet-halisaha-vcn** satırına tıklayın
6. Açılan sayfada aşağıda **Security Lists** başlığı var; oradaki güvenlik
   listesinin adına tıklayın

💡 Neden alt ağın üzerinden gidiyoruz: bir VCN'de birden fazla güvenlik
listesi olur (sihirbaz özel alt ağ için ayrı bir tane kuruyor). Bu yolla
kuralları **doğrudan sunucunuzun bağlı olduğu** listeye eklediğinizden
emin olursunuz; yanlış listeye eklenen kural hiçbir işe yaramaz ve
hata da vermez.

7. Mavi **Add Ingress Rules** düğmesine basın

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
