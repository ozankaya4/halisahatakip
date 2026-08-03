from .models import Bildirim


def unread_notifications(request):
    """Üst çubuktaki okunmamış bildirim rozeti."""
    if not request.user.is_authenticated:
        return {"okunmamis_bildirim": 0}
    return {
        "okunmamis_bildirim": Bildirim.objects.filter(
            alici=request.user, okundu=False
        ).count()
    }
