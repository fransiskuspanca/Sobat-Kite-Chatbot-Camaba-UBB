import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
os.environ.setdefault("MUAT_MODEL", "0")
django.setup()
