"""Bangun ulang index dari isi basis data.

Memanggil faq.actions.jalankan_reindex — jalur yang SAMA dipakai tombol di
admin, supaya perilaku keduanya tidak pernah menyimpang.
"""

from django.core.management.base import BaseCommand, CommandError

from faq import actions
from faq.models import IndexVersion


class Command(BaseCommand):
    help = "Bangun ulang index embedding dari tabel Faq + FaqVariasi."

    def add_arguments(self, parser):
        parser.add_argument("--ambang", type=float, default=None,
                            help="Ambang Acc@1 regression gate (default 0.85)")
        parser.add_argument("--paksa", action="store_true",
                            help="Pasang index walau regression gate gagal")
        parser.add_argument("--rollback", type=int, metavar="VERSI",
                            help="Aktifkan kembali versi index lama")

    def handle(self, *args, **opts):
        if opts["rollback"] is not None:
            return self._rollback(opts["rollback"])

        entri, _ = actions.kumpulkan_entri()
        self.stdout.write(f"Meng-encode {len(entri)} vektor…")

        try:
            st = actions.jalankan_reindex(ambang=opts["ambang"],
                                          paksa=opts["paksa"],
                                          pengguna="cli")
        except RuntimeError as e:
            raise CommandError(str(e))

        self.stdout.write(st.pesan)
        for g in (st.gagal or [])[:10]:
            self.stdout.write(self.style.WARNING(
                f"  ✗ {g['query'][:50]!r} → faq {g['dapat_faq_id']} "
                f"(harusnya {g['harapan'][:40]!r})"))

        if st.berhasil is False:
            raise CommandError(
                "Regression gate GAGAL — versi lama tetap melayani. "
                "Perbaiki entri penyebab, atau jalankan ulang dengan --paksa.")

        self.stdout.write(self.style.SUCCESS(f"✅ {st.pesan}"))

    def _rollback(self, versi):
        try:
            iv = actions.rollback(versi, pengguna="cli")
        except IndexVersion.DoesNotExist:
            raise CommandError(f"Versi {versi} tidak ditemukan.")
        self.stdout.write(self.style.SUCCESS(
            f"✅ Index dikembalikan ke v{iv.versi} "
            f"({iv.jumlah_vektor} vektor, {iv.jumlah_answer} jawaban)"))
