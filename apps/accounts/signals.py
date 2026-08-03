from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profil


@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="profil_olustur")
def profil_olustur(sender, instance, created, **kwargs):
    """Her kullanıcı için profil kaydının var olmasını garanti eder."""
    if created:
        Profil.objects.get_or_create(kullanici=instance)
