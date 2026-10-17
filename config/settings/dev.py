"""Pengembangan lokal — SQLite supaya tidak perlu PostgreSQL di laptop.

Skema yang dipakai identik; PostgreSQL tetap target produksi.
"""

import os

from .base import *  # noqa: F401,F403
from .base import BASE_DIR

DEBUG = True
ALLOWED_HOSTS = ["*"]

if os.environ.get("DB_ENGINE", "sqlite") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
