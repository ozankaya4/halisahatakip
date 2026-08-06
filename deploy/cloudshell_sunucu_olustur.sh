#!/usr/bin/env bash
#
# Oracle Cloud Shell'de sunucuyu komutla oluşturur.
#
# Konsoldaki düğmeleri aramak yerine bunu kullanın: arayüz değişse de
# komutlar değişmiyor.
#
# KULLANIM (Cloud Shell içinde):
#     bash sunucu_olustur.sh
#
# Betik hiçbir şeyi sessizce yapmaz: önce ne yapacağını yazar, onay ister.

set -euo pipefail

# Ayarlar komut satırından geçilebilir, dosyayı düzenlemeye gerek yok:
#     OCPU=1 BELLEK_GB=6 bash cloudshell_sunucu_olustur.sh
#     TEKRAR=50 BEKLEME=300 bash cloudshell_sunucu_olustur.sh
INSTANCE_ADI="${INSTANCE_ADI:-halisaha}"
SHAPE="${SHAPE:-VM.Standard.A1.Flex}"
OCPU="${OCPU:-2}"
BELLEK_GB="${BELLEK_GB:-12}"
DISK_GB="${DISK_GB:-100}"
SSH_ACIK_ANAHTAR="${SSH_ACIK_ANAHTAR:-${HOME}/halisaha_anahtar.pub}"

# Kapasite bulunamazsa kaç tur denensin ve turlar arasında kaç saniye
# beklensin. ARM kapasitesi gün içinde açılıp kapanıyor; ısrar işe yarıyor.
TEKRAR="${TEKRAR:-1}"
BEKLEME="${BEKLEME:-300}"

bilgi() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
uyari() { printf '\033[1;33m!!\033[0m %s\n' "$1"; }
hata()  { printf '\n\033[1;31mHATA:\033[0m %s\n' "$1" >&2; exit 1; }

# --- 1. Kiracı (tenancy) kimliği -----------------------------------------
TENANCY="${OCI_TENANCY:-}"
[[ -n "${TENANCY}" ]] || hata "OCI_TENANCY boş. Bu betik Oracle Cloud Shell içinde çalıştırılmalı."
bilgi "Kiracı bulundu"

# --- 2. SSH açık anahtarı -------------------------------------------------
# Anahtar, sunucuya parolasız ve güvenli girmenizi sağlayan dosya çifti.
# Yoksa burada oluşturuyoruz; kendi bilgisayarınızda bir şey yapmanıza
# gerek yok.
if [[ ! -f "${SSH_ACIK_ANAHTAR}" ]]; then
    uyari "Sunucuya bağlanmak için bir SSH anahtarı gerekiyor, henüz yok."
    echo
    echo "  Anahtar nedir: sunucuya parola yerine kullanılan, iki dosyadan"
    echo "  oluşan bir kimlik. Biri gizli (sizde kalır), biri açık"
    echo "  (sunucuya konur). Şimdi burada oluşturabilirim."
    echo
    read -rp "Anahtar şimdi oluşturulsun mu? (evet/hayir): " ANAHTAR_ONAY
    [[ "${ANAHTAR_ONAY}" == "evet" ]] || hata "Anahtar olmadan devam edilemez."

    GIZLI_ANAHTAR="${SSH_ACIK_ANAHTAR%.pub}"

    # Oracle Cloud Shell FIPS kipinde çalışıyor ve ed25519'a izin vermiyor
    # ("ED25519 keys are not allowed in FIPS mode"). Önce ed25519 deneyip,
    # reddedilirse FIPS'in kabul ettiği RSA 4096'ya düşüyoruz. RSA 4096
    # de fazlasıyla güvenli; tek farkı anahtar dosyasının büyük olması.
    if ssh-keygen -t ed25519 -f "${GIZLI_ANAHTAR}" -N "" -C "halisaha" >/dev/null 2>&1; then
        bilgi "Anahtar oluşturuldu (ed25519)."
    else
        uyari "Bu ortam ed25519'a izin vermiyor (FIPS kipi). RSA 4096 kullanılıyor."
        rm -f "${GIZLI_ANAHTAR}" "${SSH_ACIK_ANAHTAR}"
        ssh-keygen -t rsa -b 4096 -f "${GIZLI_ANAHTAR}" -N "" -C "halisaha" >/dev/null \
            || hata "Anahtar oluşturulamadı. Çıktıyı Claude'a yapıştırın."
        bilgi "Anahtar oluşturuldu (RSA 4096)."
    fi
    echo "    gizli: ${GIZLI_ANAHTAR}"
    echo "    açık : ${SSH_ACIK_ANAHTAR}"
fi

grep -q '^ssh-' "${SSH_ACIK_ANAHTAR}" \
    || hata "${SSH_ACIK_ANAHTAR} geçerli bir açık anahtar gibi görünmüyor (ssh- ile başlamalı)."
bilgi "SSH açık anahtarı hazır"

# --- 3. Genel (public) alt ağ --------------------------------------------
bilgi "Genel alt ağ aranıyor"
SUBNET=$(oci network subnet list \
    --compartment-id "${TENANCY}" --all \
    --query "data[?\"prohibit-public-ip-on-vnic\"==\`false\`].id | [0]" \
    --raw-output 2>/dev/null || true)

if [[ -z "${SUBNET}" || "${SUBNET}" == "null" ]]; then
    hata "Genel alt ağ bulunamadı.

Önce ağı oluşturun: konsolda
    Networking > Virtual cloud networks > Start VCN Wizard
    > Create VCN with Internet Connectivity
Sonra bu betiği tekrar çalıştırın. (ADIM_ADIM.md, B6a)"
fi

SUBNET_ADI=$(oci network subnet get --subnet-id "${SUBNET}" \
    --query 'data."display-name"' --raw-output)
bilgi "Alt ağ: ${SUBNET_ADI}"

# --- 4. Ubuntu 24.04 ARM görüntüsü ---------------------------------------
bilgi "Ubuntu 24.04 (ARM) görüntüsü aranıyor"
IMAGE=$(oci compute image list \
    --compartment-id "${TENANCY}" \
    --operating-system "Canonical Ubuntu" \
    --operating-system-version "24.04" \
    --shape "${SHAPE}" \
    --sort-by TIMECREATED --sort-order DESC \
    --query 'data[0].id' --raw-output)

[[ -n "${IMAGE}" && "${IMAGE}" != "null" ]] || hata "Uygun Ubuntu görüntüsü bulunamadı."
bilgi "Görüntü bulundu"

# --- 5. Kullanılabilirlik alanları ---------------------------------------
mapfile -t ADLAR < <(oci iam availability-domain list \
    --compartment-id "${TENANCY}" --query 'data[].name' --raw-output \
    | tr -d '[]", ' | grep -v '^$')

[[ ${#ADLAR[@]} -gt 0 ]] || hata "Kullanılabilirlik alanı listelenemedi."

# --- 6. Özet ve onay ------------------------------------------------------
cat <<OZET

──────────────────────────────────────────────────────────────
 Oluşturulacak sunucu:

   Ad          : ${INSTANCE_ADI}
   Şekil       : ${SHAPE}  (${OCPU} OCPU / ${BELLEK_GB} GB)
   Disk        : ${DISK_GB} GB
   Alt ağ      : ${SUBNET_ADI}
   Genel IP    : atanacak
   Denenecek AD: ${#ADLAR[@]} adet

 Hepsi Always Free sınırları içinde.
──────────────────────────────────────────────────────────────

OZET

read -rp "Devam edilsin mi? (evet/hayir): " ONAY
[[ "${ONAY}" == "evet" ]] || { echo "Vazgeçildi."; exit 0; }

# --- 7. Sırayla her AD'de dene -------------------------------------------
# ARM kapasitesi sık tükeniyor. İki katmanlı deniyoruz: önce her
# kullanılabilirlik alanı, sonra (istenirse) belli aralıklarla baştan.
INSTANCE_ID=""
TUR=1

while :; do
    for AD in "${ADLAR[@]}"; do
        bilgi "Deneniyor: ${AD}  (tur ${TUR}/${TEKRAR})"
        if CIKTI=$(oci compute instance launch \
            --availability-domain "${AD}" \
            --compartment-id "${TENANCY}" \
            --display-name "${INSTANCE_ADI}" \
            --shape "${SHAPE}" \
            --shape-config "{\"ocpus\":${OCPU},\"memoryInGBs\":${BELLEK_GB}}" \
            --image-id "${IMAGE}" \
            --subnet-id "${SUBNET}" \
            --assign-public-ip true \
            --boot-volume-size-in-gbs "${DISK_GB}" \
            --metadata "{\"ssh_authorized_keys\":\"$(cat "${SSH_ACIK_ANAHTAR}")\"}" \
            --wait-for-state RUNNING \
            2>&1); then
            INSTANCE_ID=$(echo "${CIKTI}" | grep -o '"id": "ocid1.instance[^"]*"' | head -1 | cut -d'"' -f4)
            bilgi "Sunucu oluşturuldu."
            break 2
        else
            if echo "${CIKTI}" | grep -qiE "capacity|LimitExceeded"; then
                uyari "${AD}: kapasite yok."
                continue
            fi
            echo "${CIKTI}" >&2
            hata "Beklenmeyen hata. Yukarıdaki mesajı Claude'a yapıştırın."
        fi
    done

    if (( TUR >= TEKRAR )); then
        break
    fi
    uyari "Tur ${TUR} bitti. ${BEKLEME} saniye sonra yeniden denenecek. (Ctrl+C ile durdurun)"
    sleep "${BEKLEME}"
    TUR=$(( TUR + 1 ))
done

if [[ -z "${INSTANCE_ID}" ]]; then
    hata "Kapasite bulunamadı (${SHAPE}, ${OCPU} OCPU / ${BELLEK_GB} GB).

Sırayla şunları deneyin:

  1) Daha küçük ARM isteyin (çok daha kolay bulunuyor):
       OCPU=1 BELLEK_GB=6 bash cloudshell_sunucu_olustur.sh

  2) Israrla deneyin. Kapasite gün içinde açılıp kapanıyor:
       TEKRAR=50 BEKLEME=300 bash cloudshell_sunucu_olustur.sh
     (5 dakikada bir, ~4 saat boyunca dener. Cloud Shell oturumu
      kapanırsa komut da durur; sekmeyi açık tutun.)

  3) AMD'ye geçin. Her zaman müsait, 1 GB RAM:
       SHAPE=VM.Standard.E2.1.Micro OCPU=1 BELLEK_GB=1 \\
         bash cloudshell_sunucu_olustur.sh
     Bu durumda Claude'a haber verin: 1 GB RAM'de PostgreSQL yerine
     SQLite kullanmak ve takas alanı eklemek gerekiyor."
fi

# --- 8. Genel IP ----------------------------------------------------------
IP=$(oci compute instance list-vnics --instance-id "${INSTANCE_ID}" \
    --query 'data[0]."public-ip"' --raw-output)

cat <<SON

──────────────────────────────────────────────────────────────
 ✅ Sunucu hazır.

   Genel IP : ${IP}

 Sıradaki adımlar:

 1) Güvenlik kuralları (80 ve 443). Aşağıdaki iki komutu
    Cloud Shell'de çalıştırabilirsiniz — konsolda tıklamaya gerek yok:

    bash guvenlik_kurallari.sh

 2) Namecheap'te iki A kaydı: @ ve www -> ${IP}
    (ADIM_ADIM.md, Bölüm D)

 3) Sunucuya bağlanın. En kolayı buradan, Cloud Shell'den:

    ssh -i ~/halisaha_anahtar ubuntu@${IP}

    İlk seferde "Are you sure you want to continue connecting?"
    diye sorar; "yes" yazıp Enter'a basın.
──────────────────────────────────────────────────────────────

SON
