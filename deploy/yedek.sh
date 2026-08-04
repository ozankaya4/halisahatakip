#!/usr/bin/env bash
#
# Halısaha Takip — günlük yedek. cron tarafından çağrılır.
#
# Veritabanı ile medya AYRI dosyalara alınır: medya nadiren değişir,
# veritabanı her gün. 14 günden eski yedekler silinir.
#
# ÖNEMLİ: Sohbet mesajları uçtan uca şifreli. Bu yedek onları da kapsar,
# ama şifre çözme anahtarları yalnızca kullanıcıların tarayıcısında.
# Yani yedekten mesaj metni geri getirilemez; getirilmesi de istenmiyor.

set -euo pipefail

UYGULAMA_DIZINI="/srv/halisaha"
YEDEK_DIZINI="/var/backups/halisaha"
VERITABANI="halisaha"
SAKLAMA_GUN=14

TARIH=$(date +%Y-%m-%d_%H%M)
mkdir -p "${YEDEK_DIZINI}"

# --- Veritabanı -----------------------------------------------------------
sudo -u postgres pg_dump --format=custom "${VERITABANI}" \
    > "${YEDEK_DIZINI}/veritabani_${TARIH}.dump"

# --- Medya ----------------------------------------------------------------
# Dün değişen bir şey yoksa yeni arşiv üretmeyelim: disk boşuna dolmasın.
if [[ -d "${UYGULAMA_DIZINI}/media" ]]; then
    SON_ARSIV=$(find "${YEDEK_DIZINI}" -name 'medya_*.tar.gz' -printf '%T@ %p\n' 2>/dev/null \
                | sort -rn | head -1 | cut -d' ' -f2- || true)
    DEGISIKLIK=1
    if [[ -n "${SON_ARSIV}" ]]; then
        if [[ -z $(find "${UYGULAMA_DIZINI}/media" -newer "${SON_ARSIV}" -type f -print -quit) ]]; then
            DEGISIKLIK=0
        fi
    fi
    if [[ ${DEGISIKLIK} -eq 1 ]]; then
        tar -czf "${YEDEK_DIZINI}/medya_${TARIH}.tar.gz" \
            -C "${UYGULAMA_DIZINI}" media
    fi
fi

chmod 600 "${YEDEK_DIZINI}"/*.dump "${YEDEK_DIZINI}"/*.tar.gz 2>/dev/null || true

# --- Eskileri temizle -----------------------------------------------------
find "${YEDEK_DIZINI}" -type f -mtime "+${SAKLAMA_GUN}" -delete

KALAN=$(du -sh "${YEDEK_DIZINI}" | cut -f1)
echo "$(date '+%F %T') yedek tamam (${TARIH}), toplam: ${KALAN}"
