#!/usr/bin/env bash
#
# Ağı (VCN + internet çıkışı + genel alt ağ) komutla oluşturur.
#
#     bash cloudshell_ag_olustur.sh
#
# Konsoldaki "Create VCN" formu YALNIZCA boş bir VCN oluşturur: alt ağ da,
# internet geçidi de, yönlendirme kuralı da gelmez. Sunucunun internete
# çıkabilmesi için dördü birden gerekiyor. Bu betik hepsini kurar.
#
# Betik tekrar tekrar çalıştırılabilir: var olanı bulur, eksik olanı ekler.

set -euo pipefail

VCN_ADI="halisaha-vcn"
IGW_ADI="halisaha-igw"
SUBNET_ADI="halisaha-genel-alt-ag"
VCN_CIDR="10.0.0.0/16"
SUBNET_CIDR="10.0.0.0/24"

bilgi() { printf '\n\033[1;32m==>\033[0m %s\n' "$1"; }
uyari() { printf '\033[1;33m!!\033[0m %s\n' "$1"; }
hata()  { printf '\n\033[1;31mHATA:\033[0m %s\n' "$1" >&2; exit 1; }

TENANCY="${OCI_TENANCY:-}"
[[ -n "${TENANCY}" ]] || hata "Bu betik Oracle Cloud Shell içinde çalıştırılmalı."

# =========================================================================
# 1. VCN
# =========================================================================
bilgi "VCN aranıyor: ${VCN_ADI}"
VCN_ID=$(oci network vcn list --compartment-id "${TENANCY}" --all \
    --query "data[?\"display-name\"=='${VCN_ADI}'].id | [0]" --raw-output 2>/dev/null || true)

if [[ -n "${VCN_ID}" && "${VCN_ID}" != "null" ]]; then
    bilgi "Var olan VCN kullanılıyor."
else
    # Konsolda yarım kalmış başka VCN'ler varsa haber verelim (zararsız,
    # ücretsiz; ama karışıklık olmasın).
    ESKILER=$(oci network vcn list --compartment-id "${TENANCY}" --all \
        --query 'data[]."display-name"' --raw-output 2>/dev/null || true)
    if [[ -n "${ESKILER}" && "${ESKILER}" != "[]" ]]; then
        uyari "Hesapta zaten VCN(ler) var:"
        echo "${ESKILER}" | tr -d '[]",' | tr ' ' '\n' | grep -v '^$' | sed 's/^/      /'
        echo
        echo "   Bunlar yarım kalmış olabilir. Yenisini oluşturmak sorun değil,"
        echo "   ücret çıkarmaz; eskileri sonra konsoldan silebilirsiniz."
        echo
        read -rp "   Yeni VCN oluşturulsun mu? (evet/hayir): " C
        [[ "${C}" == "evet" ]] || { echo "Vazgeçildi."; exit 0; }
    fi

    bilgi "VCN oluşturuluyor (${VCN_CIDR})"
    # Yeni CLI --cidr-blocks, eski sürümler --cidr-block bekliyor.
    VCN_ID=$(oci network vcn create \
        --compartment-id "${TENANCY}" \
        --display-name "${VCN_ADI}" \
        --cidr-blocks "[\"${VCN_CIDR}\"]" \
        --wait-for-state AVAILABLE \
        --query 'data.id' --raw-output 2>/dev/null) \
      || VCN_ID=$(oci network vcn create \
        --compartment-id "${TENANCY}" \
        --display-name "${VCN_ADI}" \
        --cidr-block "${VCN_CIDR}" \
        --wait-for-state AVAILABLE \
        --query 'data.id' --raw-output)

    [[ -n "${VCN_ID}" && "${VCN_ID}" != "null" ]] || hata "VCN oluşturulamadı."
    bilgi "VCN hazır."
fi

# =========================================================================
# 2. Internet Gateway — sunucunun internete çıkış kapısı
# =========================================================================
bilgi "Internet Gateway aranıyor"
IGW_ID=$(oci network internet-gateway list \
    --compartment-id "${TENANCY}" --vcn-id "${VCN_ID}" --all \
    --query 'data[0].id' --raw-output 2>/dev/null || true)

if [[ -n "${IGW_ID}" && "${IGW_ID}" != "null" ]]; then
    bilgi "Var olan Internet Gateway kullanılıyor."
else
    bilgi "Internet Gateway oluşturuluyor"
    IGW_ID=$(oci network internet-gateway create \
        --compartment-id "${TENANCY}" \
        --vcn-id "${VCN_ID}" \
        --display-name "${IGW_ADI}" \
        --is-enabled true \
        --wait-for-state AVAILABLE \
        --query 'data.id' --raw-output)
    [[ -n "${IGW_ID}" && "${IGW_ID}" != "null" ]] || hata "Internet Gateway oluşturulamadı."
    bilgi "Internet Gateway hazır."
fi

# =========================================================================
# 3. Yönlendirme kuralı — "internete giden trafik IGW'den çıksın"
# =========================================================================
RT_ID=$(oci network vcn get --vcn-id "${VCN_ID}" \
    --query 'data."default-route-table-id"' --raw-output)

bilgi "Yönlendirme kuralı ayarlanıyor"
oci network route-table update --rt-id "${RT_ID}" --force \
    --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"${IGW_ID}\"}]" \
    >/dev/null

# Doğrula: kural gerçekten yazıldı mı? (JSON alan adları CLI sürümüne göre
# değişebiliyor; sessizce boş geçmesindense burada patlasın.)
KURAL=$(oci network route-table get --rt-id "${RT_ID}" \
    --query 'data."route-rules"[?destination==`0.0.0.0/0`] | length(@)' --raw-output)
[[ "${KURAL}" -ge 1 ]] || hata "Yönlendirme kuralı yazılamadı. Bu mesajı Claude'a yapıştırın."
bilgi "Yönlendirme kuralı tamam."

# =========================================================================
# 4. Genel (public) alt ağ
# =========================================================================
bilgi "Genel alt ağ aranıyor"
SUBNET_ID=$(oci network subnet list \
    --compartment-id "${TENANCY}" --vcn-id "${VCN_ID}" --all \
    --query "data[?\"prohibit-public-ip-on-vnic\"==\`false\`].id | [0]" \
    --raw-output 2>/dev/null || true)

if [[ -n "${SUBNET_ID}" && "${SUBNET_ID}" != "null" ]]; then
    bilgi "Var olan genel alt ağ kullanılıyor."
else
    bilgi "Genel alt ağ oluşturuluyor (${SUBNET_CIDR})"
    # prohibit-public-ip-on-vnic false = "bu alt ağdaki makineler genel IP
    # alabilir". Konsolda takıldığınız anahtarın karşılığı tam olarak bu.
    SUBNET_ID=$(oci network subnet create \
        --compartment-id "${TENANCY}" \
        --vcn-id "${VCN_ID}" \
        --display-name "${SUBNET_ADI}" \
        --cidr-block "${SUBNET_CIDR}" \
        --prohibit-public-ip-on-vnic false \
        --route-table-id "${RT_ID}" \
        --wait-for-state AVAILABLE \
        --query 'data.id' --raw-output)
    [[ -n "${SUBNET_ID}" && "${SUBNET_ID}" != "null" ]] || hata "Alt ağ oluşturulamadı."
    bilgi "Genel alt ağ hazır."
fi

# =========================================================================
# 5. Son kontrol
# =========================================================================
GENEL_MI=$(oci network subnet get --subnet-id "${SUBNET_ID}" \
    --query 'data."prohibit-public-ip-on-vnic"' --raw-output)
[[ "${GENEL_MI}" == "false" ]] \
    || hata "Alt ağ genel değil. Sunucu genel IP alamaz."

cat <<SON

──────────────────────────────────────────────────────────────
 ✅ Ağ hazır.

   VCN              : ${VCN_ADI}   (${VCN_CIDR})
   Internet Gateway : var
   Yönlendirme      : 0.0.0.0/0 -> Internet Gateway
   Genel alt ağ     : ${SUBNET_ADI}  (${SUBNET_CIDR})

 Sırada sunucuyu oluşturmak var:

     bash cloudshell_sunucu_olustur.sh
──────────────────────────────────────────────────────────────

SON
