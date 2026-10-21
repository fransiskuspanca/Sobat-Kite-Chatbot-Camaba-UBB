"""Ambil paket data tambahan (hasil simulasi) dari GitHub lalu reindex.

    python manage.py sinkron_data                   # dari SINKRON_SUMBER
    python manage.py sinkron_data --sumber data/sinkron
    python manage.py sinkron_data --tanpa-reindex

Dijalankan cron tiap 15 menit. Tanpa paket baru, perintah ini hanya membaca
daftar.json lalu selesai. Reindex memakai regression gate biasa: kalau gagal,
index lama tetap melayani dan reindex malam mencoba lagi. Lihat faq/sinkron.py.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from faq import sinkron


class Command(BaseCommand):
    help = "Terapkan paket data tambahan dari GitHub, lalu reindex."

    def add_arguments(self, parser):
        parser.add_argument("--sumber", default=settings.SINKRON_SUMBER,
                            help="URL folder (diakhiri /) atau folder lokal")
        parser.add_argument("--tanpa-reindex", action="store_true")

    def handle(self, *args, **opts):
        from retrieval.indexer import muat_hard_eval

        hard = muat_hard_eval(settings.ARTIFACTS_DIR / "hard_eval.json") or {}
        terlarang = {sinkron._norm(q) for qs in hard.values() for q in qs}
        try:
            n = sinkron.jalankan(opts["sumber"], terlarang, tulis=self.stdout.write)
        except (OSError, ValueError) as e:
            raise CommandError(f"Gagal membaca paket dari {opts['sumber']}: {e}")
        if not n or opts["tanpa_reindex"]:
            return

        from faq import actions
        try:
            st = actions.jalankan_reindex(pengguna="sinkron")
        except RuntimeError as e:
            raise CommandError(str(e))
        if st.berhasil is False:
            raise CommandError(
                f"Data tersimpan, tetapi regression gate gagal ({st.pesan}). "
                "Index lama tetap melayani; reindex malam akan mencoba lagi.")
        self.stdout.write(self.style.SUCCESS(f"✅ {st.pesan}"))
