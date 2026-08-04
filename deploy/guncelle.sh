#!/usr/bin/env bash
#
# Halısaha Takip — güncelleme (yeni sürümü yayına alma).
#
#     sudo bash /srv/halisaha/deploy/guncelle.sh
#
# Göç öncesi otomatik yedek alır; bir şey ters giderse geri dönebilirsiniz.

set -euo pipefail

UYGULAMA_DIZINI="/srv/halisaha"
KULLANICI="halisaha"
PY="${UYGULAMA_DIZINI}/.venv/bin/python"
PIP="${UYGULAMA_DIZINI}/.venv/bin/pip"

bilgi() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
hata()  { printf '\n\033[1;31mHATA:\033[0m %s\n' "$1" >&2; exit 1; }

[[ $EUID -eq 0 ]] || hata "root olarak çalıştırın (sudo bash ...)."

bilgi "Göç öncesi yedek"
/usr/local/bin/halisaha-yedek

bilgi "Yeni sürüm çekiliyor"
cd "${UYGULAMA_DIZINI}"
ONCEKI=$(sudo -u "${KULLANICI}" git rev-parse --short HEAD)
sudo -u "${KULLANICI}" git pull --ff-only
SONRAKI=$(sudo -u "${KULLANICI}" git rev-parse --short HEAD)

if [[ "${ONCEKI}" == "${SONRAKI}" ]]; then
    bilgi "Değişiklik yok (${ONCEKI}). Yine de yeniden başlatılıyor."
else
    bilgi "${ONCEKI} -> ${SONRAKI}"
fi

bilgi "Bağımlılıklar"
"${PIP}" install --quiet --upgrade pip wheel
"${PIP}" install --quiet -r requirements.txt
"${PIP}" install --quiet 'psycopg[binary]==3.2.9'

bilgi "Dağıtım denetimi"
sudo -u "${KULLANICI}" "${PY}" manage.py check --deploy --fail-level WARNING

bilgi "Veritabanı göçleri"
sudo -u "${KULLANICI}" "${PY}" manage.py migrate --noinput

bilgi "Statik dosyalar"
sudo -u "${KULLANICI}" "${PY}" manage.py collectstatic --noinput

bilgi "Servis yeniden başlatılıyor"
systemctl restart halisaha
sleep 2

if systemctl is-active --quiet halisaha; then
    bilgi "Yayında. Sürüm: ${SONRAKI}"
else
    hata "Servis başlamadı. Günlük: journalctl -u halisaha -n 50"
fi
