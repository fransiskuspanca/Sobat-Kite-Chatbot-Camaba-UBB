"""Dev server untuk proses API.

Django tidak membaca env var DJANGO_URLCONF, jadi urlconf ditetapkan di sini.
Dipakai untuk menguji API secara lokal; di produksi wsgi_api + gunicorn yang
menanganinya.
"""

from .dev import *  # noqa: F401,F403

ROOT_URLCONF = "config.urls_api"
