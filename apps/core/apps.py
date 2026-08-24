from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Çekirdek"

    def ready(self):
        # Üretim ayarı denetimleri; "manage.py check --deploy" ile çalışır.
        from . import checks  # noqa: F401
