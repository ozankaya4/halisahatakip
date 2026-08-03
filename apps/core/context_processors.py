from django.conf import settings

TEMA_COOKIE = "hst_tema"
GECERLI_TEMALAR = {"acik", "koyu"}


def site_chrome(request):
    """Her şablonda gereken kabuk bilgileri (tema, site adı)."""
    tema = request.COOKIES.get(TEMA_COOKIE, "acik")
    if tema not in GECERLI_TEMALAR:
        tema = "acik"
    return {
        "tema": tema,
        "karsi_tema": "koyu" if tema == "acik" else "acik",
        "site_adi": "Halısaha Defteri",
        "debug_modu": settings.DEBUG,
    }
