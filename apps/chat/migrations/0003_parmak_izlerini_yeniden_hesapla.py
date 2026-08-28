"""
Saklanan parmak izlerini açık anahtardan yeniden hesaplar.

Parmak izi eskiden istemciden geldiği gibi saklanıyordu, yani anahtarla
tutarlı olmak zorunda değildi. Artık sunucu hesaplıyor; bu göç eski satırları
da aynı hâle getiriyor.

Uyuşmayan satırlar günlüğe yazılıyor. Küçük bir kurulumda bu birkaç saniyelik
bir kontrol ama sonucu değerli: uyuşmayan bir satır ya eski bir istemci
hatası ya da anahtarın elle değiştirildiği anlamına gelir.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.db import migrations

guvenlik_log = logging.getLogger("halisaha.guvenlik")


def _parmak_izi(acik_jwk: dict) -> str:
    # services.parmak_izi_hesapla ile aynı; göçler kod değişiminden
    # etkilenmesin diye kopyalanıyor (Django göçlerinde alışılmış yol).
    veri = f"{acik_jwk['n']}.{acik_jwk['e']}".encode("utf-8")
    onalti = hashlib.sha256(veri).hexdigest()[:32]
    return " ".join(onalti[i : i + 4] for i in range(0, 32, 4)).upper()


def ileri(apps, schema_editor):
    AnahtarCifti = apps.get_model("chat", "AnahtarCifti")
    guncellenecek = []
    for kayit in AnahtarCifti.objects.all():
        try:
            jwk = json.loads(kayit.acik_anahtar)
            yeni = _parmak_izi(jwk)
        except (ValueError, KeyError, TypeError):
            guvenlik_log.warning(
                "Parmak izi hesaplanamadı, atlandı: anahtar_cifti=%s", kayit.pk
            )
            continue
        if kayit.parmak_izi != yeni:
            guvenlik_log.warning(
                "Saklanan parmak izi anahtarla uyuşmuyor, düzeltiliyor: "
                "anahtar_cifti=%s",
                kayit.pk,
            )
            kayit.parmak_izi = yeni
            guncellenecek.append(kayit)
    if guncellenecek:
        AnahtarCifti.objects.bulk_update(guncellenecek, ["parmak_izi"])


def geri(apps, schema_editor):
    # Geri alınacak bir şey yok: eski değerler zaten anahtardan türemiyordu,
    # dolayısıyla geri yazılacak "doğru" bir hâlleri de yok.
    pass


class Migration(migrations.Migration):
    dependencies = [("chat", "0002_anahtardegisimi")]
    operations = [migrations.RunPython(ileri, geri)]
