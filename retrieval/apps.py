"""Pemuatan model + penjagaannya.

Ini jebakan nomor satu Django + model ML. ready() juga dipanggil saat
migrate/collectstatic/shell/test. Memuat model 600 MB hanya untuk menjalankan
migrasi itu pemborosan dan memperlambat deploy secara signifikan.
"""

import logging
import os
import sys

from django.apps import AppConfig

log = logging.getLogger(__name__)

# Perintah manage.py yang TIDAK butuh model.
PERINTAH_TANPA_MODEL = {
    "migrate", "makemigrations", "collectstatic", "shell", "dbshell",
    "createsuperuser", "test", "check", "showmigrations", "sqlmigrate",
    "loaddata", "dumpdata", "import_colab", "changepassword", "flush",
    "squashmigrations", "startapp", "diffsettings",
}


def perlu_model(argv=None, env=None) -> bool:
    """Putuskan apakah proses ini benar-benar melayani request.

    Dipisah jadi fungsi murni supaya bisa diuji tanpa menjalankan Django.
    """
    argv = sys.argv if argv is None else argv
    env = os.environ if env is None else env

    if PERINTAH_TANPA_MODEL & set(argv):
        return False

    # pytest / runner lain
    if any("pytest" in str(a) for a in argv[:1]):
        return False

    # Hindari pemuatan ganda oleh autoreload dev server: proses induk
    # menetapkan RUN_MAIN=true hanya di proses anak yang benar-benar melayani.
    if "runserver" in argv and env.get("RUN_MAIN") != "true":
        return False

    return True


class RetrievalConfig(AppConfig):
    name = "retrieval"
    verbose_name = "Mesin retrieval"

    def ready(self):
        from django.conf import settings

        if not getattr(settings, "MUAT_MODEL", False):
            log.info("MUAT_MODEL=0 — engine tidak dimuat (normal untuk Fase 0/1).")
            return

        if not perlu_model():
            log.debug("Perintah tidak butuh model — pemuatan dilewati.")
            return

        from .engine import muat_engine_global
        muat_engine_global(settings.ARTIFACTS_DIR)
