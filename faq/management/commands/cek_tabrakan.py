"""Cari pasangan FAQ yang praktis sama di SELURUH basis pengetahuan.

Cek tabrakan di admin hanya berjalan saat menyimpan satu entri. Perintah ini
menyapu semuanya sekaligus — berguna untuk membereskan data lama sebelum
go-live (checklist: "entri kembar sudah digabung").

Bedakan dari Acc@1 yang rendah: kalau model masih model dasar, Acc@1 rendah
BUKAN karena tabrakan, dan perintah ini akan menunjukkannya (sedikit/tidak
ada pasangan mencurigakan).
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Cari pasangan FAQ yang terlalu mirip di seluruh basis pengetahuan."

    def add_arguments(self, parser):
        parser.add_argument("--ambang", type=float, default=0.90,
                            help="Batas kemiripan (default 0.90)")
        parser.add_argument("--batas", type=int, default=40,
                            help="Maksimal pasangan ditampilkan")

    def handle(self, *args, **opts):
        import numpy as np

        from faq.models import Faq
        from faq.services import muat_engine

        engine = muat_engine()
        if engine is None:
            raise CommandError(
                "Model tidak tersedia. Jalankan: manage.py siapkan_model")

        daftar = list(Faq.objects.filter(aktif=True).order_by("id"))
        if len(daftar) < 2:
            raise CommandError("Butuh minimal 2 FAQ aktif.")

        self.stdout.write(f"Meng-encode {len(daftar)} pertanyaan…")
        vek = engine.encode([f.pertanyaan for f in daftar], is_query=False)

        # Matriks kemiripan; ambil segitiga atas agar tiap pasangan sekali saja.
        skor = vek @ vek.T
        np.fill_diagonal(skor, -1.0)
        i_atas, j_atas = np.triu_indices(len(daftar), k=1)
        nilai = skor[i_atas, j_atas]

        urut = np.argsort(-nilai)
        pasangan = [(i_atas[k], j_atas[k], float(nilai[k])) for k in urut
                    if nilai[k] >= opts["ambang"]][:opts["batas"]]

        if not pasangan:
            self.stdout.write(self.style.SUCCESS(
                f"\n✅ Tidak ada pasangan dengan kemiripan ≥ {opts['ambang']}. "
                "Basis pengetahuan bersih dari entri kembar."))
            return

        self.stdout.write(self.style.WARNING(
            f"\n⚠️  {len(pasangan)} pasangan mirip (≥ {opts['ambang']}):\n"))
        for i, j, s in pasangan:
            a, b = daftar[i], daftar[j]
            self.stdout.write(f"  {s:.3f}")
            self.stdout.write(f"    [{a.id}] {a.pertanyaan[:68]}")
            self.stdout.write(f"    [{b.id}] {b.pertanyaan[:68]}")
            self.stdout.write("")

        self.stdout.write(
            "Dua entri yang praktis sama membuat retrieval ambigu SELAMANYA.\n"
            "Gabungkan salah satunya menjadi variasi cara bertanya pada yang lain.")
