"""Tes perintah `tanya` — jalur pengujian manual Fase 0."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


def test_tanpa_index_pesan_jelas(monkeypatch):
    """Tanpa index aktif, pesan harus mengarahkan, bukan traceback."""
    import faq.management.commands.tanya as modul

    # Model dianggap ada supaya yang diuji benar-benar cek index.
    monkeypatch.setattr(modul.Command, "_siapkan",
                        modul.Command._siapkan)  # tetap asli
    with pytest.raises(CommandError) as e:
        call_command("tanya", "apa itu ubb")
    # Boleh mengeluh soal model ATAU soal index — keduanya pesan yang menuntun.
    assert "reindex" in str(e.value) or "siapkan_model" in str(e.value)
