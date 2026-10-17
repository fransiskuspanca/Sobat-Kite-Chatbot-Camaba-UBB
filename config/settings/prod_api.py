"""Produksi — proses API publik (gunicorn :8000).

Hanya /v1/* + /healthz. Proses ini TIDAK memuat /admin/* sama sekali.
"""

from .prod import *  # noqa: F401,F403

ROOT_URLCONF = "config.urls_api"
