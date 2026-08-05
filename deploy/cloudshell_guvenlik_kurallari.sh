#!/usr/bin/env bash
#
# 80 ve 443 portlarını Oracle güvenlik listesine ekler.
#
#     bash guvenlik_kurallari.sh
#
# NEDEN BETİK: "oci network security-list update" komutu gelen kuralları
# EKLEMEZ, TÜMÜNÜ DEĞİŞTİRİR. Elle çalıştırılan basit bir update komutu
# 22 numaralı SSH kuralını da siler ve sunucuya bir daha bağlanamazsınız.
# Bu betik önce mevcut kuralları okuyup üzerine ekliyor.

set -euo pipefail

bilgi() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
uyari() { printf '\033[1;33m!!\033[0m %s\n' "$1"; }
hata()  { printf '\n\033[1;31mHATA:\033[0m %s\n' "$1" >&2; exit 1; }

TENANCY="${OCI_TENANCY:-}"
[[ -n "${TENANCY}" ]] || hata "Bu betik Oracle Cloud Shell içinde çalıştırılmalı."

# --- Genel alt ağı ve ona bağlı güvenlik listesini bul --------------------
bilgi "Genel alt ağ aranıyor"
SUBNET=$(oci network subnet list --compartment-id "${TENANCY}" --all \
    --query "data[?\"prohibit-public-ip-on-vnic\"==\`false\`].id | [0]" \
    --raw-output 2>/dev/null || true)
[[ -n "${SUBNET}" && "${SUBNET}" != "null" ]] || hata "Genel alt ağ bulunamadı."

SUBNET_ADI=$(oci network subnet get --subnet-id "${SUBNET}" \
    --query 'data."display-name"' --raw-output)

# Alt ağın KENDİ güvenlik listesini alıyoruz. VCN'de birden fazla liste
# olabiliyor; yanlış olana eklenen kural hiçbir işe yaramaz, hata da vermez.
SL=$(oci network subnet get --subnet-id "${SUBNET}" \
    --query 'data."security-list-ids"[0]' --raw-output)
[[ -n "${SL}" && "${SL}" != "null" ]] || hata "Alt ağa bağlı güvenlik listesi bulunamadı."

bilgi "Alt ağ: ${SUBNET_ADI}"

# --- Mevcut kuralları oku -------------------------------------------------
MEVCUT=$(oci network security-list get --security-list-id "${SL}" \
    --query 'data."ingress-security-rules"' 2>/dev/null)

ONCE=$(echo "${MEVCUT}" | jq 'length')
bilgi "Mevcut gelen kural sayısı: ${ONCE}"

echo "${MEVCUT}" | jq -r '.[] |
    "    - port \(.["tcp-options"]["destination-port-range"].min // "hepsi") <- \(.source)"' \
    2>/dev/null || true

# --- 80 ve 443'ü ekle (varsa tekrar ekleme) ------------------------------
YENI=$(echo "${MEVCUT}" | jq '
  # Betik iki kez çalışırsa kural çiftlenmesin diye, TAM OLARAK bizim
  # ekleyeceğimizle eşleşenleri çıkarıyoruz. Başka kaynaklardan gelen ya da
  # geniş aralıklı (örn. 1-1000) kurallara dokunmuyoruz.
  map(select(
    ((.source == "0.0.0.0/0")
     and ((.["tcp-options"]["destination-port-range"].min // 0) as $p
          | $p == 80 or $p == 443)
     and ((.["tcp-options"]["destination-port-range"].max // 0) as $u
          | $u == 80 or $u == 443)
    ) | not
  ))
  + [
    {
      "protocol": "6",
      "source": "0.0.0.0/0",
      "source-type": "CIDR_BLOCK",
      "is-stateless": false,
      "description": "HTTP (Let'"'"'s Encrypt dogrulamasi ve yonlendirme)",
      "tcp-options": {"destination-port-range": {"min": 80, "max": 80}}
    },
    {
      "protocol": "6",
      "source": "0.0.0.0/0",
      "source-type": "CIDR_BLOCK",
      "is-stateless": false,
      "description": "HTTPS",
      "tcp-options": {"destination-port-range": {"min": 443, "max": 443}}
    }
  ]')

SONRA=$(echo "${YENI}" | jq 'length')

# --- Güvenlik kontrolü: SSH kuralı duruyor mu? ---------------------------
# TCP/22'ye gerçekten izin veren kuralları sayıyoruz:
#   - protocol "all", ya da
#   - protocol "6" (TCP) ve port aralığı 22'yi kapsıyor
#     (tcp-options yoksa tüm TCP portları açık demektir)
# ICMP gibi alakasız kuralları saymamak önemli: yanlış bir "sorun yok"
# kararı, kontrolün hiç olmamasından kötüdür.
SSH_VAR=$(echo "${YENI}" | jq '[.[] | select(
    .protocol == "all"
    or (.protocol == "6" and (
          .["tcp-options"] == null
          or .["tcp-options"]["destination-port-range"] == null
          or ((.["tcp-options"]["destination-port-range"].min <= 22)
              and (.["tcp-options"]["destination-port-range"].max >= 22))
       ))
)] | length')

if [[ "${SSH_VAR}" -eq 0 ]]; then
    hata "Yeni kural listesinde SSH (22) yok. Uygulanırsa sunucuya
bağlanamazsınız. İşlem durduruldu; bu mesajı Claude'a yapıştırın."
fi

bilgi "Kural sayısı ${ONCE} -> ${SONRA} olacak (SSH kuralı korunuyor)"
read -rp "Uygulansın mı? (evet/hayir): " ONAY
[[ "${ONAY}" == "evet" ]] || { echo "Vazgeçildi."; exit 0; }

oci network security-list update \
    --security-list-id "${SL}" \
    --ingress-security-rules "${YENI}" \
    --force >/dev/null

bilgi "Kurallar eklendi."

# --- Doğrula --------------------------------------------------------------
oci network security-list get --security-list-id "${SL}" \
    --query 'data."ingress-security-rules"' \
    | jq -r '.[] |
        "    - port \(.["tcp-options"]["destination-port-range"].min // "hepsi") <- \(.source)"'

cat <<'SON'

──────────────────────────────────────────────────────────────
 Listede 22, 80 ve 443 görüyorsanız bu adım tamam.

 Sırada: Namecheap'te A kayıtları (ADIM_ADIM.md, Bölüm D)
──────────────────────────────────────────────────────────────

SON
