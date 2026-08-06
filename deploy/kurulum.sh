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

bilgi "Alan adı: ${ALAN_ADI}"

# --- Paketler -------------------------------------------------------------
bilgi "Sistem paketleri kuruluyor"
export DEBIAN_FRONTEND=noninteractive

# Paket listesi güncellenemezse devam etmenin anlamı yok.
apt-get update || hata "apt-get update başarısız. Yukarıdaki çıktıyı Claude'a yapıştırın."

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

Yukarıdaki apt çıktısının TAMAMINI Claude'a yapıştırın; hangi paketin
çakıştığı orada yazıyor.

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
if ! iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
fi
if ! iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
fi
netfilter-persistent save >/dev/null
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
mkdir -p "${UYGULAMA_DIZINI}/media" "${UYGULAMA_DIZINI}/staticfiles" /var/backups/halisaha
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
sed "s/__ALAN_ADI__/${ALAN_ADI}/g" \
    "${UYGULAMA_DIZINI}/deploy/nginx.sablon.conf" \
    > /etc/nginx/sites-available/halisaha
ln -sf /etc/nginx/sites-available/halisaha /etc/nginx/sites-enabled/halisaha
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

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
