"""Entrypoint gunicorn untuk API publik.

ROOT_URLCONF ditetapkan lewat settings (config.settings.prod_api), bukan env
var — Django tidak membaca DJANGO_URLCONF.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod_api")
application = get_wsgi_application()
