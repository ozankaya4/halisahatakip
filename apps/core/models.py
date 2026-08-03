from django.db import models


class ZamanDamgaliModel(models.Model):
    """Oluşturulma/güncellenme bilgisi taşıyan soyut temel model."""

    olusturulma = models.DateTimeField("oluşturulma", auto_now_add=True, db_index=True)
    guncellenme = models.DateTimeField("güncellenme", auto_now=True)

    class Meta:
        abstract = True
