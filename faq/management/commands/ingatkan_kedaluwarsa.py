"""Daftar FAQ yang perlu diverifikasi ulang.

Data PMB berubah tiap tahun; jawaban basi yang tampil sebagai fakta adalah
risiko yang disebut eksplisit di dokumen rencana. Dijalankan mingguan lewat
cron, hasilnya dikirim ke panitia.
"""

from datetime import date, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand

from faq.models import Faq

BATAS_BULAN_DEFAULT = 12


class Command(BaseCommand):
    help = "Daftar FAQ yang terakhir diverifikasi > N bulan lalu."

    def add_arguments(self, parser):
        parser.add_argument("--bulan", type=int, default=BATAS_BULAN_DEFAULT)
        parser.add_argument("--email", nargs="*", default=None,
                            help="Kirim ke alamat ini (default: hanya cetak)")

    def handle(self, *args, **opts):
        batas = date.today() - timedelta(days=30 * opts["bulan"])

        usang = Faq.objects.filter(aktif=True,
                                   terakhir_diverifikasi__lt=batas)
        belum = Faq.objects.filter(aktif=True,
                                   terakhir_diverifikasi__isnull=True)
        menunggu = Faq.objects.filter(aktif=True, butuh_verifikasi=True)

        baris = [
            f"Laporan kesegaran basis pengetahuan — {date.today():%d %b %Y}",
            "",
            f"Kedaluwarsa (> {opts['bulan']} bulan) : {usang.count()}",
            f"Belum pernah diverifikasi        : {belum.count()}",
            f"Menunggu persetujuan unit        : {menunggu.count()}",
        ]

        if usang.exists():
            baris += ["", f"--- Perlu diverifikasi ulang ({usang.count()}) ---"]
            for f in usang.order_by("terakhir_diverifikasi")[:30]:
                baris.append(
                    f"  [{f.terakhir_diverifikasi:%d %b %Y}] {f.pertanyaan[:70]}")

        if menunggu.exists():
            baris += ["", f"--- Menunggu persetujuan unit ({menunggu.count()}) ---"]
            for f in menunggu[:30]:
                baris.append(f"  {f.pertanyaan[:70]}")

        laporan = "\n".join(baris)
        self.stdout.write(laporan)

        penerima = opts["email"]
        if penerima:
            send_mail(
                subject=f"[Chatbot PMB UBB] Kesegaran FAQ — {date.today():%d %b %Y}",
                message=laporan,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL",
                                   "chatbot@ubb.ac.id"),
                recipient_list=penerima,
                fail_silently=False)
            self.stdout.write(self.style.SUCCESS(
                f"\n✅ Laporan dikirim ke {', '.join(penerima)}"))
