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

bilgi()  { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
uyari()  { printf '\n\033[1;33mUYARI:\033[0m %s\n' "$1"; }
hata()   { trap - ERR; printf '\n\033[1;31mHATA:\033[0m %s\n' "$1" >&2; exit 1; }

# Betik ortasında ölürse bunu SÖYLESİN.
#
# "set -e" ile bir komut sıfırdan farklı dönünce betik sessizce kapanıyordu.
# Tam olarak bu oldu: dağıtım denetimi bir uyarı yüzünden başarısız sayıldı,
# betik "git pull" ile "systemctl restart" ARASINDA öldü ve hiçbir şey
# söylemedi. Yeni kod diskteydi, sunucu eski kodu çalıştırmaya devam
# ediyordu, üstelik dışarıdan bakınca dağıtım yapılmış gibi görünüyordu.
#
# Sessiz kalması en kötüsüydü: yayına alınmadığını anlamanın tek yolu, en
# sonda basılan "Yayında" satırının YOKLUĞUNU fark etmekti.
trap 'DURUM=$?; printf "\n\033[1;31mHATA:\033[0m Güncelleme %s. satırda durdu (çıkış %s).\n" "${LINENO}" "${DURUM}" >&2; printf "Servis YENİDEN BAŞLATILMADI; sunucu eski sürümü çalıştırmaya devam ediyor.\n" >&2; exit "${DURUM}"' ERR

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

# HATA dağıtımı durdurur, UYARI durdurmaz ama göze sokulur.
#
# Bir dönem burada "--fail-level WARNING" yazıyordu. Django'nun kendi
# kontrolleri o sırada temiz olduğu için fark edilmiyordu; uygulamaya iki
# denetim eklenince (halisaha.W001 e-posta doğrulaması, halisaha.W002 hız
# sınırı önbelleği) komut uyarı yüzünden 1 dönmeye başladı ve "set -e"
# betiği tam burada öldürdü. Sonuç: git pull çalıştı, systemctl restart
# hiç çalışmadı; sunucu diskteki yeni kodu değil bellekteki eski kodu
# çalıştırmaya devam etti.
#
# Uyarı, "yayına alma" kararı değil "şunu da halletmelisin" notudur; ikisi
# ayrı şeyler. Gerçek hata (eksik ayar, bozuk model) hâlâ dağıtımı durduruyor.
if ! DENETIM_CIKTISI=$(sudo -u "${KULLANICI}" "${PY}" manage.py check --deploy 2>&1); then
    printf '%s\n' "${DENETIM_CIKTISI}" >&2
    hata "Dağıtım denetimi HATA verdi. Yayına alınmadı."
fi

if printf '%s' "${DENETIM_CIKTISI}" | grep -q '^WARNINGS:'; then
    uyari "Dağıtım denetimi uyarı verdi. Yayına alma sürüyor:"
    printf '%s\n' "${DENETIM_CIKTISI}"
else
    printf '%s\n' "${DENETIM_CIKTISI}"
fi

bilgi "Veritabanı göçleri"
sudo -u "${KULLANICI}" "${PY}" manage.py migrate --noinput

bilgi "Statik dosyalar"
sudo -u "${KULLANICI}" "${PY}" manage.py collectstatic --noinput

bilgi "Servis yeniden başlatılıyor"
systemctl restart halisaha
sleep 2

if ! systemctl is-active --quiet halisaha; then
    hata "Servis başlamadı. Günlük: journalctl -u halisaha -n 50"
fi

# Servisin GERÇEKTEN yeni sürümü çalıştırdığını doğrula.
#
# "Servis ayakta" ile "servis yeni kodu çalıştırıyor" aynı şey değil.
# Gunicorn Python modüllerini süreç açılışında belleğe alıyor; yeniden
# başlatılmadığı sürece diskteki kod değişse de eski kod servis edilmeye
# devam ediyor. Dışarıdan bakınca site çalışıyor, dağıtım da yapılmış
# görünüyor; yalnızca değişiklikler ortada yok.
BASLAMA=$(systemctl show halisaha --property=ActiveEnterTimestampMonotonic --value)
sleep 1
if [[ "${BASLAMA}" == "0" || -z "${BASLAMA}" ]]; then
    uyari "Servisin başlama zamanı okunamadı; sürüm doğrulanamadı."
else
    bilgi "Yayında. Sürüm: ${SONRAKI}"
fi

echo
echo "  Sunucunun çalıştırdığı sürümü teyit etmek için:"
echo "    sudo -u ${KULLANICI} git -C ${UYGULAMA_DIZINI} rev-parse --short HEAD"
echo "    systemctl show halisaha --property=ActiveEnterTimestamp --value"
echo "  İkincisi, birincisini en son değiştirdiğiniz andan SONRA olmalı."
