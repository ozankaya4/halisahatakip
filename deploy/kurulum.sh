#!/usr/bin/env bash
#
# Halısaha Takip — Oracle Cloud (Ubuntu 24.04 ARM) ilk kurulum betiği.
#
# Sunucuda root olarak çalıştırın:
#     sudo bash /srv/halisaha/deploy/kurulum.sh
#
# Betik defalarca çalıştırılabilir; var olan şeyleri bozmaz.

set -euo pipefail

UYGULAMA_DIZINI="/srv/halisaha"
KULLANICI="halisaha"
VERITABANI="halisaha"
DB_KULLANICI="halisaha"

bilgi() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
uyari() { printf '\n\033[1;33m!!\033[0m %s\n' "$1"; }
hata()  { printf '\n\033[1;31mHATA:\033[0m %s\n' "$1" >&2; exit 1; }

[[ $EUID -eq 0 ]] || hata "Bu betik root olarak çalıştırılmalı (sudo bash ...)."

# --- Alan adı -------------------------------------------------------------
if [[ ! -f "${UYGULAMA_DIZINI}/deploy/sunucu.env" ]]; then
    hata "deploy/sunucu.env bulunamadı. sunucu.env.ornek dosyasını kopyalayıp doldurun."
fi
# shellcheck disable=SC1091
source "${UYGULAMA_DIZINI}/deploy/sunucu.env"
[[ -n "${ALAN_ADI:-}" ]] || hata "sunucu.env içinde ALAN_ADI boş."

# Parola DATABASE_URL'nin içine gömülüyor. URL'de özel anlamı olan bir
# karakter içerirse (özellikle "/"), Python adresi yanlış ayrıştırıyor ve
# parolanın bir kısmını port numarası sanıp şu hatayı veriyor:
#     ValueError: Port could not be cast to integer value as '...'
# Bu yüzden "openssl rand -base64" kullanmayın: çıktısında / ve + olabiliyor.
# Tehlikeli karakterleri saymak yerine güvenli olanları beyaz listeye
# alıyoruz: URL'de "unreserved" sayılan harf, rakam, nokta, alt tire,
# tire ve tilde. Başka her şey reddedilir. (Yasaklı karakterleri tek tek
# saymak, köşeli parantez ifadesinde kaçış kuralları yüzünden sessizce
# yanlış çalışıyordu.)
GUVENLI_PAROLA_DESENI='^[A-Za-z0-9._~-]+$'
if [[ -n "${DB_PAROLA:-}" ]] && ! [[ "${DB_PAROLA}" =~ $GUVENLI_PAROLA_DESENI ]]; then
    hata "DB_PAROLA URL'de sorun çıkaracak bir karakter içeriyor.
İzin verilenler: harf, rakam, nokta, alt tire, tire, tilde.

Güvenli bir parola üretip ikisini birden güncelleyin:

    PAROLA=\$(openssl rand -hex 24)
    sudo -u postgres psql -c \"ALTER ROLE halisaha PASSWORD '\${PAROLA}';\"
    sudo sed -i \"s|^DATABASE_URL=.*|DATABASE_URL=postgres://halisaha:\${PAROLA}@localhost:5432/halisaha|\" ${UYGULAMA_DIZINI}/.env
    sudo sed -i \"s|^DB_PAROLA=.*|DB_PAROLA=\${PAROLA}|\" ${UYGULAMA_DIZINI}/deploy/sunucu.env"
fi

# .env içindeki DATABASE_URL'de yer tutucu köşeli parantez kalmış mı?
if [[ -f "${UYGULAMA_DIZINI}/.env" ]] \
   && grep -q '^DATABASE_URL=.*[<>]' "${UYGULAMA_DIZINI}/.env"; then
    hata ".env içindeki DATABASE_URL satırında < veya > karakteri var.

Kılavuzdaki <...> işaretleri 'buraya kendi değerinizi yazın' demek;
köşeli parantezler silinmeli. Satır tam olarak şuna benzemeli:

    DATABASE_URL=postgres://halisaha:PAROLANIZ@localhost:5432/halisaha"
fi

bilgi "Alan adı: ${ALAN_ADI}"

# --- Paketler -------------------------------------------------------------
bilgi "Sistem paketleri kuruluyor"
export DEBIAN_FRONTEND=noninteractive

# Paket listesi güncellenemezse devam etmenin anlamı yok.
apt-get update || hata "apt-get update başarısız. Yukarıdaki çıktıya bakın."

# Paketleri gruplar hâlinde kuruyoruz. Tek uzun komut çalıştırıp "-qq" ile
# susturmak, hata çıktığında hangi paketin sorun olduğunu gizliyordu;
# geriye yalnızca "you have held broken packages" gibi sebebi anlaşılmayan
# bir satır kalıyordu. Grup grup kurunca sorunlu grup hemen belli oluyor.
paket_kur() {
    local etiket="$1"; shift
    printf '    - %s\n' "${etiket}"
    if ! apt-get install -y "$@"; then
        hata "Paket kurulumu başarısız: ${etiket}
Paketler: $*

Yukarıdaki apt çıktısının TAMAMINI okuyun; hangi paketin çakıştığı
orada yazıyor.

Sık işe yarayan iki komut:
    sudo apt-get -f install
    sudo apt-get update --fix-missing"
    fi
}

paket_kur "Python"     python3 python3-venv python3-dev build-essential
paket_kur "PostgreSQL" postgresql postgresql-contrib libpq-dev
paket_kur "Web"        nginx certbot python3-certbot-nginx
paket_kur "Yardımcı"   git curl iptables-persistent unattended-upgrades

# --- Güvenlik duncarı -----------------------------------------------------
# Oracle'ın Ubuntu görüntüsü iptables ile 22 dışındaki her şeyi kapatır.
# Bu, kurulumda herkesin takıldığı yer: Security List'te portu açsanız bile
# makinenin kendi iptables kuralı isteği düşürür. İkisi de gerekli.
bilgi "Güvenlik duvarı kuralları (iptables)"

# Kuralın sırası kritik: iptables zinciri yukarıdan aşağı işletir ve ilk
# eşleşen kural kazanır. Oracle'ın Ubuntu görüntüsünde zincirin sonunda
# "REJECT all" var. ACCEPT kuralımız ondan SONRA eklenirse hiç
# değerlendirilmez; kural listede görünür ama trafik yine düşer.
#
# Eskiden sabit "6. sıraya ekle" deniyordu; bu, zincirin her görüntüde
# aynı sırada olduğunu varsayıyordu. Artık REJECT/DROP kuralını arayıp
# onun hemen öncesine ekliyoruz.
kural_ekle() {
    local port="$1"

    # Kuralın VAR OLMASI yetmiyor, DOĞRU SIRADA olması gerekiyor. Bu yüzden
    # "varsa dokunma" demiyoruz: önce bu porta ait tüm kuralları siliyoruz,
    # sonra REJECT'in önüne bir tane ekliyoruz.
    #
    # Neden böyle: eski sürüm sabit 6. sıraya ekliyordu ve "zaten var mı"
    # kontrolü de hatalıydı. Sonuç: REJECT 5. sıradayken kurallar 6-11'e
    # yığılıyor, hiçbiri değerlendirilmiyor, üstelik her çalıştırmada bir
    # kopya daha ekleniyordu. Liste doluydu ama port kapalıydı.
    local silinen=0
    while iptables -C INPUT -m state --state NEW -p tcp --dport "${port}" -j ACCEPT 2>/dev/null; do
        iptables -D INPUT -m state --state NEW -p tcp --dport "${port}" -j ACCEPT
        silinen=$(( silinen + 1 ))
    done

    local konum
    konum=$(iptables -L INPUT --line-numbers -n \
            | awk '$2=="REJECT" || $2=="DROP" {print $1; exit}')

    if [[ -n "${konum}" ]]; then
        iptables -I INPUT "${konum}" -m state --state NEW -p tcp --dport "${port}" -j ACCEPT
        printf '    - %s açıldı (%s. sıraya, REJECT kuralının önüne; %s eski kopya silindi)\n' \
            "${port}" "${konum}" "${silinen}"
    else
        iptables -A INPUT -m state --state NEW -p tcp --dport "${port}" -j ACCEPT
        printf '    - %s açıldı (zincirde REJECT yok, sona eklendi; %s eski kopya silindi)\n' \
            "${port}" "${silinen}"
    fi
}

kural_ekle 80
kural_ekle 443
netfilter-persistent save >/dev/null

# Doğrulama: kuralın var olması DEĞİL, REJECT'ten ÖNCE olması gerekiyor.
# Yanlış sırada duran bir kural da listede görünür ama hiçbir işe yaramaz.
REJECT_SIRA=$(iptables -L INPUT --line-numbers -n \
              | awk '$2=="REJECT" || $2=="DROP" {print $1; exit}')
if [[ -n "${REJECT_SIRA}" ]]; then
    for port in 80 443; do
        PORT_SIRA=$(iptables -L INPUT --line-numbers -n \
                    | awk -v p="dpt:${port}" '$0 ~ p && $2=="ACCEPT" {print $1; exit}')
        if [[ -z "${PORT_SIRA}" ]]; then
            uyari "${port} için ACCEPT kuralı bulunamadı."
        elif (( PORT_SIRA > REJECT_SIRA )); then
            uyari "${port} kuralı REJECT'ten SONRA (${PORT_SIRA} > ${REJECT_SIRA}). Bu port kapalı sayılır."
        else
            printf '    - %s doğrulandı (sıra %s, REJECT %s)\n' "${port}" "${PORT_SIRA}" "${REJECT_SIRA}"
        fi
    done
fi
uyari "Oracle konsolunda Security List'e de 80/443 ingress kuralı eklemeyi unutmayın."

# --- Kullanıcı ------------------------------------------------------------
if ! id -u "${KULLANICI}" >/dev/null 2>&1; then
    bilgi "Sistem kullanıcısı oluşturuluyor: ${KULLANICI}"
    adduser --system --group --home "${UYGULAMA_DIZINI}" --no-create-home "${KULLANICI}"
fi
# nginx soketi okuyabilsin
usermod -aG "${KULLANICI}" www-data

# --- PostgreSQL -----------------------------------------------------------
bilgi "PostgreSQL hazırlanıyor"
systemctl enable --now postgresql

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_KULLANICI}'" | grep -q 1; then
    [[ -n "${DB_PAROLA:-}" ]] || hata "sunucu.env içinde DB_PAROLA boş."
    sudo -u postgres psql -qc \
        "CREATE ROLE ${DB_KULLANICI} LOGIN PASSWORD '${DB_PAROLA}';"
    bilgi "Veritabanı rolü oluşturuldu."
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${VERITABANI}'" | grep -q 1; then
    sudo -u postgres createdb -O "${DB_KULLANICI}" "${VERITABANI}"
    bilgi "Veritabanı oluşturuldu."
fi

# --- Python ortamı --------------------------------------------------------
bilgi "Sanal ortam ve bağımlılıklar"
if [[ ! -d "${UYGULAMA_DIZINI}/.venv" ]]; then
    python3 -m venv "${UYGULAMA_DIZINI}/.venv"
fi
"${UYGULAMA_DIZINI}/.venv/bin/pip" install --quiet --upgrade pip wheel
"${UYGULAMA_DIZINI}/.venv/bin/pip" install --quiet -r "${UYGULAMA_DIZINI}/requirements.txt"
# Üretimde PostgreSQL kullanıyoruz; sürücü requirements.txt'de yorumlu.
"${UYGULAMA_DIZINI}/.venv/bin/pip" install --quiet 'psycopg[binary]==3.2.9'

# --- Dizinler ve izinler --------------------------------------------------
bilgi "Dizin izinleri"
# .gunicorn: systemd ProtectSystem=strict yüzünden uygulama dizini salt
# okunur; gunicorn'un denetim soketi için bu klasör önceden var olmalı ve
# servis dosyasında ReadWritePaths ile açılmalı.
mkdir -p "${UYGULAMA_DIZINI}/media" "${UYGULAMA_DIZINI}/staticfiles" \
         "${UYGULAMA_DIZINI}/.gunicorn" /var/backups/halisaha
chown -R "${KULLANICI}:${KULLANICI}" "${UYGULAMA_DIZINI}"
chown root:root /var/backups/halisaha
chmod 750 /var/backups/halisaha
# Yüklenen dosyalar asla çalıştırılabilir olmasın.
chmod -R u=rwX,g=rX,o= "${UYGULAMA_DIZINI}/media"

# Depo "ubuntu" kullanıcısıyla klonlanıp sonra halisaha'ya devredildiği için
# git "dubious ownership" diyip guncelle.sh'ı reddedebiliyor. Şimdiden izin ver.
sudo -u "${KULLANICI}" git config --global --add safe.directory "${UYGULAMA_DIZINI}" 2>/dev/null || true

if [[ -f "${UYGULAMA_DIZINI}/.env" ]]; then
    chown "${KULLANICI}:${KULLANICI}" "${UYGULAMA_DIZINI}/.env"
    chmod 600 "${UYGULAMA_DIZINI}/.env"
else
    uyari ".env yok. deploy/sunucu.env.ornek'i /srv/halisaha/.env olarak kopyalayıp doldurun."
fi

# --- Django ---------------------------------------------------------------
if [[ -f "${UYGULAMA_DIZINI}/.env" ]]; then
    bilgi "Göçler ve statik dosyalar"
    sudo -u "${KULLANICI}" "${UYGULAMA_DIZINI}/.venv/bin/python" \
        "${UYGULAMA_DIZINI}/manage.py" migrate --noinput
    sudo -u "${KULLANICI}" "${UYGULAMA_DIZINI}/.venv/bin/python" \
        "${UYGULAMA_DIZINI}/manage.py" collectstatic --noinput
fi

# --- systemd --------------------------------------------------------------
bilgi "systemd servisi"
cp "${UYGULAMA_DIZINI}/deploy/halisaha.service" /etc/systemd/system/halisaha.service
systemctl daemon-reload
systemctl enable halisaha

# --- nginx ----------------------------------------------------------------
bilgi "nginx yapılandırması"

# DİKKAT: Bu dosyayı koşulsuz üretmek, certbot'un eklediği HTTPS bloğunu
# (listen 443, ssl_certificate satırları) siliyordu. Betik ikinci kez
# çalıştırıldığında site aniden erişilemez hâle geliyordu: Django
# SECURE_SSL_REDIRECT ile HTTPS'e yönlendiriyor ama nginx artık 443'ü
# dinlemiyor. Bu yüzden certbot'un dokunduğu bir dosyanın üzerine yazmıyoruz.
NGINX_HEDEF="/etc/nginx/sites-available/halisaha"

if [[ -f "${NGINX_HEDEF}" ]] && grep -qE "listen 443|managed by Certbot" "${NGINX_HEDEF}"; then
    uyari "nginx yapılandırması certbot tarafından düzenlenmiş; korunuyor."
    echo "    Şablonu yeniden uygulamak isterseniz:"
    echo "      sudo cp ${NGINX_HEDEF} ${NGINX_HEDEF}.yedek"
    echo "      sudo rm ${NGINX_HEDEF}"
    echo "      sudo bash ${UYGULAMA_DIZINI}/deploy/kurulum.sh"
    echo "      sudo certbot install --nginx --cert-name ${ALAN_ADI}"
else
    sed "s/__ALAN_ADI__/${ALAN_ADI}/g" \
        "${UYGULAMA_DIZINI}/deploy/nginx.sablon.conf" \
        > "${NGINX_HEDEF}"
    bilgi "nginx yapılandırması şablondan üretildi."
fi
ln -sf /etc/nginx/sites-available/halisaha /etc/nginx/sites-enabled/halisaha
rm -f /etc/nginx/sites-enabled/default
nginx -t

# DİKKAT: reload DEĞİL, restart.
# Yukarıda "usermod -aG halisaha www-data" ile nginx'i halisaha grubuna
# ekliyoruz; medya dosyaları grup okumasına açık (g=rX, o=). Ama bir sürecin
# ek grupları yalnızca BAŞLARKEN okunur. reload yapılırsa nginx ana süreci
# eski gruplarıyla devam eder, medya klasörünü okuyamaz ve X-Accel-Redirect
# ile yönlendirilen her fotoğraf sessizce 403/404 döner.
# Belirti: site çalışır, ama profil ve maç fotoğrafları hiç görünmez.
systemctl restart nginx

# Gerçekten okuyabiliyor mu? "Kural eklendi" demek yetmiyor, deneyelim.
if ! sudo -u www-data test -x "${UYGULAMA_DIZINI}"; then
    uyari "www-data ${UYGULAMA_DIZINI} klasörüne giremiyor; fotoğraflar görünmez."
elif ! sudo -u www-data test -r "${UYGULAMA_DIZINI}/media"; then
    uyari "www-data medya klasörünü okuyamıyor; fotoğraflar görünmez."
else
    bilgi "nginx medya klasörünü okuyabiliyor."
fi

# --- Yedekleme ------------------------------------------------------------
bilgi "Günlük yedek görevi"
cp "${UYGULAMA_DIZINI}/deploy/yedek.sh" /usr/local/bin/halisaha-yedek
chmod 700 /usr/local/bin/halisaha-yedek
cat > /etc/cron.d/halisaha-yedek <<'CRON'
# Her gece 03:30'da veritabanı + medya yedeği
30 3 * * * root /usr/local/bin/halisaha-yedek >/var/log/halisaha-yedek.log 2>&1
CRON

# --- Otomatik güvenlik güncellemeleri ------------------------------------
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

bilgi "Uygulama başlatılıyor"
systemctl restart halisaha
sleep 2
systemctl is-active --quiet halisaha \
    && bilgi "halisaha servisi çalışıyor." \
    || uyari "Servis başlamadı: journalctl -u halisaha -n 50"

cat <<SON

──────────────────────────────────────────────────────────────
 Kurulum bitti. Sırada:

 1) DNS: ${ALAN_ADI} ve www.${ALAN_ADI} A kaydı bu sunucunun
    genel IP adresine baksın. Yayılmayı bekleyin:
        dig +short ${ALAN_ADI}

 2) HTTPS sertifikası (DNS yayıldıktan SONRA):
        sudo certbot --nginx -d ${ALAN_ADI} -d www.${ALAN_ADI}

 3) .env içinde SECURE_SSL_REDIRECT=True yapıp yeniden başlatın:
        sudo systemctl restart halisaha

 4) Nihai yöneticiyi oluşturun:
        cd /srv/halisaha
        sudo -u halisaha .venv/bin/python manage.py ilk_yonetici

 5) Google OAuth yönlendirme adreslerini güncelleyin (KURULUM.md 7. adım).
──────────────────────────────────────────────────────────────

SON
