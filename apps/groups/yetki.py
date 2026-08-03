"""
Grup yetki denetimleri.

Görünümler `genel_id` yerine doğrudan `grup` nesnesi alır; böylece her
görünümün başında yetki kontrolünü tekrar yazmak gerekmez ve bir görünümde
kontrolü unutmak mümkün olmaz.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Grup


def uye_gerekli(gorunum):
    """Grubun onaylı üyesi (veya nihai yönetici) olmayı şart koşar."""

    @wraps(gorunum)
    @login_required
    def sarmalayici(request, genel_id, *args, **kwargs):
        grup = get_object_or_404(Grup, genel_id=genel_id)
        if not (request.user.is_superuser or grup.uye_mi(request.user)):
            raise PermissionDenied("Bu grubun üyesi değilsiniz.")
        return gorunum(request, grup, *args, **kwargs)

    return sarmalayici


def yonetici_gerekli(gorunum):
    """Grup yöneticisi (veya nihai yönetici) olmayı şart koşar."""

    @wraps(gorunum)
    @login_required
    def sarmalayici(request, genel_id, *args, **kwargs):
        grup = get_object_or_404(Grup, genel_id=genel_id)
        if not grup.yonetici_mi(request.user):
            raise PermissionDenied("Bu işlem için grup yöneticisi olmalısınız.")
        return gorunum(request, grup, *args, **kwargs)

    return sarmalayici
