"""Ambil paket data tambahan (hasil simulasi) dari GitHub lalu reindex.

    python manage.py sinkron_data                   # dari SINKRON_SUMBER
    python manage.py sinkron_data --sumber data/sinkron
    python manage.py sinkron_data --tanpa-reindex

Dijalankan cron tiap 15 menit. Tanpa paket baru, perintah ini hanya membaca
daftar.json lalu selesai. Reindex memakai regression gate biasa: kalau gagal,
paket itu dibatalkan dan index lama tetap melayani. Lihat faq/sinkron.py.
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
        uji = None if opts["tanpa_reindex"] else self._uji
        try:
            sinkron.jalankan(opts["sumber"], terlarang, tulis=self.stdout.write, uji=uji)
        except (OSError, ValueError) as e:
            raise CommandError(f"Gagal membaca paket dari {opts['sumber']}: {e}")

    def _uji(self):
        """Reindex dengan regression gate. Lolos = index baru sudah aktif."""
        from faq import actions
        try:
            st = actions.jalankan_reindex(pengguna="sinkron")
        except RuntimeError as e:
            return False, {"pesan": str(e)[:300]}
        info = {"pesan": st.pesan[:300], "acc_at_1": st.acc_at_1,
                "versi_index": st.versi_baru if st.berhasil else None}
        if st.berhasil:
            self.stdout.write(self.style.SUCCESS(f"✅ {st.pesan}"))
        return bool(st.berhasil), info
