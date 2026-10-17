"""Tes penjagaan pemuatan model (Bagian 9.1) — jebakan nomor satu Django+ML."""

import pytest

from retrieval.apps import perlu_model


@pytest.mark.parametrize("cmd", ["migrate", "makemigrations", "collectstatic",
                                 "shell", "createsuperuser", "test", "check",
                                 "import_colab", "dumpdata"])
def test_perintah_manajemen_tidak_memuat_model(cmd):
    assert perlu_model(["manage.py", cmd], {}) is False


def test_gunicorn_memuat_model():
    assert perlu_model(["gunicorn", "config.wsgi_api"], {}) is True


def test_runserver_hanya_di_proses_anak():
    """Tanpa ini autoreload memuat model DUA KALI (1,2 GB, bukan 600 MB)."""
    assert perlu_model(["manage.py", "runserver"], {}) is False
    assert perlu_model(["manage.py", "runserver"], {"RUN_MAIN": "true"}) is True


def test_pytest_tidak_memuat_model():
    assert perlu_model(["/usr/bin/pytest"], {}) is False
