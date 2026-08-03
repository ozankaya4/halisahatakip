from django import forms
from django.utils import timezone

from apps.core.images import MAC_FOTOGRAFI, gorseli_isle

from .models import Mac


class YerelDatetimeAlani(forms.DateTimeField):
    """<input type="datetime-local"> ile uyumlu tarih-saat alanı."""

    widget = forms.DateTimeInput(
        attrs={"type": "datetime-local", "step": 300}, format="%Y-%m-%dT%H:%M"
    )
    input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"]


class MacFormu(forms.ModelForm):
    baslangic = YerelDatetimeAlani(label="Tarih ve saat")
    yoklama_son = YerelDatetimeAlani(
        label="Yoklama son tarihi (isteğe bağlı)",
        required=False,
        help_text="Boş bırakılırsa yoklama maç saatine kadar açık kalır.",
    )

    class Meta:
        model = Mac
        fields = ["baslangic", "konum", "sure_dakika", "notlar", "yoklama_acik", "yoklama_son"]
        labels = {
            "konum": "Saha / konum (isteğe bağlı)",
            "sure_dakika": "Süre (dakika)",
            "notlar": "Not (isteğe bağlı)",
            "yoklama_acik": "Yoklama anketi açılsın",
        }
        widgets = {
            "konum": forms.TextInput(
                attrs={"placeholder": "Örn. Ataşehir Spor Tesisleri, 3 No'lu Saha"}
            ),
            "notlar": forms.TextInput(attrs={"placeholder": "Örn. Forma rengi beyaz"}),
            "sure_dakika": forms.NumberInput(attrs={"min": 30, "max": 180, "step": 15}),
        }

    def clean_sure_dakika(self):
        sure = self.cleaned_data.get("sure_dakika") or 60
        if not (30 <= sure <= 180):
            raise forms.ValidationError("Süre 30 ile 180 dakika arasında olmalı.")
        return sure

    def clean(self):
        temiz = super().clean()
        baslangic = temiz.get("baslangic")
        yoklama_son = temiz.get("yoklama_son")

        if baslangic and self.instance.pk is None and baslangic < timezone.now():
            self.add_error("baslangic", "Geçmiş bir tarihe maç eklenemez.")
        if baslangic and yoklama_son and yoklama_son > baslangic:
            self.add_error(
                "yoklama_son", "Yoklama son tarihi maç saatinden sonra olamaz."
            )
        return temiz


class CokluDosyaGirdisi(forms.ClearableFileInput):
    """Django 5, çoklu yüklemeyi açıkça izin verilmedikçe reddeder."""

    allow_multiple_selected = True


class CokluDosyaAlani(forms.FileField):
    """Seçilen her dosyayı ayrı ayrı doğrulayan alan."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", CokluDosyaGirdisi())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        tekil_temizle = super().clean
        if isinstance(data, (list, tuple)):
            return [tekil_temizle(dosya, initial) for dosya in data]
        return tekil_temizle(data, initial)


class FotografFormu(forms.Form):
    dosyalar = CokluDosyaAlani(
        label="Fotoğraflar",
        required=False,
        widget=CokluDosyaGirdisi(
            attrs={
                "multiple": True,
                "accept": "image/jpeg,image/png,image/webp,image/gif",
            }
        ),
        help_text="JPG, PNG, WEBP veya GIF · dosya başına en fazla 8 MB.",
    )
    aciklama = forms.CharField(
        label="Açıklama (isteğe bağlı)",
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Örn. İkinci yarı"}),
    )

    def temiz_gorseller(self, dosyalar):
        """
        Her dosyayı doğrular ve yeniden kodlar.

        Tek bir dosya bile reddedilirse tamamı reddedilir; böylece kullanıcı
        hangi dosyanın sorunlu olduğunu görür ve yarım yükleme oluşmaz.
        """
        temiz = []
        for dosya in dosyalar:
            icerik, _ = gorseli_isle(dosya, MAC_FOTOGRAFI)
            temiz.append(icerik)
        return temiz


class KadroFormu(forms.Form):
    """Yöneticinin maç sonrası gerçek kadroyu işaretlemesi için."""

    oynayanlar = forms.CharField(required=False, widget=forms.HiddenInput)
