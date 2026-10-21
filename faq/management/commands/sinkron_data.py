"""Ambil paket data tambahan (hasil simulasi) dari GitHub lalu reindex.

    python manage.py sinkron_data                   # dari SINKRON_SUMBER
    python manage.py sinkron_data --sumber data/sinkron
    python manage.py sinkron_data --tanpa-reindex

Dijalankan cron tiap 15 menit. Tanpa paket baru, perintah ini hanya membaca
daftar.json lalu selesai. Setelah tiap paket, reindex dengan regression gate
yang ambangnya akurasi index aktif: kalau akurasi turun, paket itu dibatalkan
dan index lama tetap melayani. Lihat faq/sinkron.py.
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
        """Reindex dengan regression gate. Lolos = index baru sudah aktif.

        Ambangnya akurasi index yang sedang aktif (minimal ambang biasa):
        paket boleh tidak menambah akurasi, tetapi tidak boleh menguranginya.
        Tanpa ini, tiap paket yang lolos sendiri-sendiri bisa menggerus
        akurasi sedikit demi sedikit sampai tepat di ambang.
        """
        from faq import actions
        from faq.models import IndexVersion
        aktif = (IndexVersion.objects.filter(aktif=True)
                 .values_list("acc_at_1", flat=True).first())
        ambang = max(actions.ambang_default(), (aktif or 0) - 1e-9)
        try:
            st = actions.jalankan_reindex(ambang=ambang, pengguna="sinkron")
        except RuntimeError as e:
            return False, {"pesan": str(e)[:300]}
        info = {"pesan": st.pesan[:300], "acc_at_1": st.acc_at_1,
                "versi_index": st.versi_baru if st.berhasil else None}
        if st.berhasil:
            self.stdout.write(self.style.SUCCESS(f"✅ {st.pesan}"))
        return bool(st.berhasil), info
