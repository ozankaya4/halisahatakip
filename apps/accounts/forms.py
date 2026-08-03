from django import forms

from apps.core.images import AVATAR, gorseli_isle

from .models import Mevki, Profil


class KayitFormu(forms.Form):
    """allauth kayıt formuna ad soyad alanı ekler."""

    ad_soyad = forms.CharField(
        label="Ad soyad",
        max_length=80,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Örn. Ozan Kaya", "autocomplete": "name"}),
    )

    def signup(self, request, user):
        ad = (self.cleaned_data.get("ad_soyad") or "").strip()
        if ad:
            user.ad_soyad = ad[:80]
            user.save(update_fields=["ad_soyad"])


class ProfilFormu(forms.ModelForm):
    ad_soyad = forms.CharField(
        label="Ad soyad",
        max_length=80,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Örn. Ozan Kaya", "autocomplete": "name"}),
    )
    avatar = forms.ImageField(
        label="Profil fotoğrafı",
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp,image/gif"}),
    )
    avatari_sil = forms.BooleanField(label="Mevcut fotoğrafı kaldır", required=False)

    class Meta:
        model = Profil
        fields = ["mevki", "forma_no", "hakkinda"]
        labels = {
            "mevki": "Mevki",
            "forma_no": "Forma numarası",
            "hakkinda": "Kısa not",
        }
        widgets = {
            "hakkinda": forms.TextInput(
                attrs={"placeholder": "Örn. Sol ayak, sakatlık sonrası dönüş"}
            ),
            "forma_no": forms.NumberInput(attrs={"min": 1, "max": 99}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mevki"].choices = Mevki.choices
        if self.instance and self.instance.kullanici_id:
            self.fields["ad_soyad"].initial = self.instance.kullanici.ad_soyad

    def clean_forma_no(self):
        no = self.cleaned_data.get("forma_no")
        if no is not None and not (1 <= no <= 99):
            raise forms.ValidationError("Forma numarası 1 ile 99 arasında olmalı.")
        return no

    def clean_avatar(self):
        """
        Doğrulama ve yeniden kodlama burada yapılır; modele yalnızca bizim
        ürettiğimiz temiz WEBP dosyası ulaşır.
        """
        dosya = self.cleaned_data.get("avatar")
        if not dosya:
            return None
        icerik, _ = gorseli_isle(dosya, AVATAR)
        return icerik

    def save(self, commit=True):
        profil = super().save(commit=False)

        ad = (self.cleaned_data.get("ad_soyad") or "").strip()
        profil.kullanici.ad_soyad = ad[:80]
        profil.kullanici.save(update_fields=["ad_soyad"])

        if self.cleaned_data.get("avatari_sil"):
            profil.avatar.delete(save=False)
            profil.avatar = None

        yeni_avatar = self.cleaned_data.get("avatar")
        if yeni_avatar:
            profil.avatar.delete(save=False)
            profil.avatar.save(yeni_avatar.name, yeni_avatar, save=False)

        if commit:
            profil.save()
        return profil
