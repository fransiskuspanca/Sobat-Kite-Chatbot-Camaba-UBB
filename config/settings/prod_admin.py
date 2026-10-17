"""Produksi — proses admin panel (gunicorn :8001, allowlist IP)."""

from .prod import *  # noqa: F401,F403

ROOT_URLCONF = "config.urls_admin"
