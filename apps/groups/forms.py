from django import forms
from django.conf import settings

from .models import Grup


class GrupFormu(forms.ModelForm):
    class Meta:
        model = Grup
        fields = ["ad", "aciklama"]
        labels = {"ad": "Grup adı", "aciklama": "Açıklama"}
        widgets = {
            "ad": forms.TextInput(attrs={"placeholder": "Örn. Perşembe Ekibi", "autofocus": True}),
            "aciklama": forms.TextInput(
                attrs={"placeholder": "Örn. Her perşembe 21:00, Ataşehir"}
            ),
        }

    def clean_ad(self):
        ad = (self.cleaned_data.get("ad") or "").strip()
        if len(ad) < 3:
            raise forms.ValidationError("Grup adı en az 3 karakter olmalı.")
        return ad


class DavetFormu(forms.Form):
    etiket = forms.CharField(
        label="Etiket (isteğe bağlı)",
        max_length=60,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Örn. WhatsApp grubu"}),
        help_text="Yalnızca sizin bu bağlantıyı hatırlamanız için.",
    )
    gun = forms.IntegerField(
        label="Geçerlilik süresi (gün)",
        min_value=1,
        max_value=90,
        initial=settings.INVITE_DEFAULT_TTL_DAYS,
    )
    max_kullanim = forms.IntegerField(
        label="Azami kullanım sayısı",
        min_value=1,
        max_value=200,
        initial=settings.INVITE_MAX_USES_DEFAULT,
    )


class KatilmaFormu(forms.Form):
    katilma_notu = forms.CharField(
        label="Yöneticiye not (isteğe bağlı)",
        max_length=200,
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "Örn. Ben Mert, Ozan'ın arkadaşıyım"}
        ),
    )
