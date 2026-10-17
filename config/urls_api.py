"""Hanya /v1/* + /healthz (Bagian 3 dokumen rencana).

Proses ini TIDAK memuat /admin/* sama sekali — kalaupun ada kerentanan di
kode admin, ia tidak terjangkau dari internet publik.
"""

from django.http import JsonResponse
from django.urls import path

from api.router import api


def healthz(request):
    """Cek ringan untuk Nginx — sengaja TIDAK menyentuh model."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("v1/", api.urls),
    path("healthz", healthz),
]
