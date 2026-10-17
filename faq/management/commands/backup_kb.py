"""Ekspor basis pengetahuan ke JSON.

Basis pengetahuan adalah hasil kerja berbulan-bulan mengurasi 260 FAQ, dan
satu VPS berarti tidak ada redundansi. Perintah ini melengkapi pg_dump dengan
salinan yang bisa dibaca manusia dan diimpor ulang lewat import_colab.
"""

import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from faq.models import Faq


class Command(BaseCommand):
    help = "Ekspor seluruh FAQ + variasi ke JSON (bisa diimpor ulang)."

    def add_arguments(self, parser):
        parser.add_argument("--keluar", default=None,
                            help="Path berkas keluaran (default: backup/kb-<tanggal>.json)")

    def handle(self, *args, **opts):
        tujuan = Path(opts["keluar"] or
                      f"backup/kb-{datetime.now():%Y-%m-%d}.json")
        tujuan.parent.mkdir(parents=True, exist_ok=True)

        data = []
        for f in Faq.objects.prefetch_related("variasi").order_by("id"):
            data.append({
                "pertanyaan": f.pertanyaan,
                "jawaban": f.jawaban,
                "kategori": f.kategori,
                "sub_kategori": f.sub_kategori,
                "sumber": f.sumber_url or f.sumber_label,
                "butuh_verifikasi": f.butuh_verifikasi,
                "terakhir_diverifikasi": (f.terakhir_diverifikasi.isoformat()
                                          if f.terakhir_diverifikasi else None),
                "aktif": f.aktif,
                "variasi": [v.teks for v in f.variasi.all()],
            })

        tujuan.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"✅ {len(data)} FAQ diekspor ke {tujuan}"))
        self.stdout.write(
            "Ingat: salin keluar dari VPS. Backup di server yang sama dengan "
            "datanya bukan backup.")
