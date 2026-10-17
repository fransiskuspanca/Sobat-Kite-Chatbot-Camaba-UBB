"""Hapus ChatLog yang lebih tua dari N bulan.

Log 3 bulan pertama adalah data latih untuk fine-tuning putaran kedua, jadi
retensi default sengaja panjang (12 bulan). Yang dibuang hanyalah log lama
yang sudah tidak berguna untuk analisis maupun pelatihan.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from percakapan.models import ChatLog

RETENSI_BULAN_DEFAULT = 12


class Command(BaseCommand):
    help = "Hapus ChatLog lebih tua dari N bulan (default 12)."

    def add_arguments(self, parser):
        parser.add_argument("--bulan", type=int, default=RETENSI_BULAN_DEFAULT)
        parser.add_argument("--dry-run", action="store_true",
                            help="Tampilkan jumlah tanpa menghapus")

    def handle(self, *args, **opts):
        batas = timezone.now() - timedelta(days=30 * opts["bulan"])
        qs = ChatLog.objects.filter(dibuat__lt=batas)
        jumlah = qs.count()

        if opts["dry_run"]:
            self.stdout.write(
                f"--dry-run: {jumlah} log lebih tua dari {opts['bulan']} bulan "
                f"(sebelum {batas:%d %b %Y}) akan dihapus.")
            return

        # Feedback ikut terhapus lewat CASCADE.
        qs.delete()
        self.stdout.write(self.style.SUCCESS(
            f"✅ {jumlah} log dihapus. Tersisa: {ChatLog.objects.count()}"))
