"""Simulasi pertanyaan camaba atas FAQ & variasi yang ada di basis data.

    python manage.py simulasi                         # uji variasi + hard eval
    python manage.py simulasi --berkas uji.xlsx       # + daftar pertanyaan sendiri
    python manage.py simulasi --log-hari 7            # + pertanyaan gagal 7 hari terakhir
    python manage.py simulasi --keluar laporan.xlsx   # simpan laporan Excel

Tidak mengubah apa pun: index aktif tetap melayani. Lihat faq/simulasi.py.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from faq import simulasi as sim
from faq.actions import kumpulkan_entri

TAMPIL_MAKS = 20


class Command(BaseCommand):
    help = "Simulasikan pertanyaan camaba dan laporkan yang salah atau rawan."

    def add_arguments(self, parser):
        parser.add_argument("--berkas", action="append", default=[],
                            help="Daftar pertanyaan (.txt/.json/.xlsx/.csv). "
                                 "Boleh diulang.")
        parser.add_argument("--log-hari", type=int, default=0,
                            help="Ikutkan pertanyaan gagal/👎 dari N hari terakhir")
        parser.add_argument("--tanpa-variasi", action="store_true",
                            help="Lewati uji variasi (leave-one-out)")
        parser.add_argument("--keluar", default="",
                            help="Simpan laporan lengkap ke berkas .xlsx")

    def handle(self, *args, **opts):
        from faq.services import muat_engine
        from retrieval.indexer import muat_hard_eval

        engine = muat_engine()
        if engine is None:
            raise CommandError(
                f"Model tidak ada di {settings.ARTIFACTS_DIR}/model/. "
                "Jalankan: python manage.py siapkan_model")
        entri, _ = kumpulkan_entri()
        if not entri:
            raise CommandError("Tidak ada FAQ aktif — jalankan import_colab dulu.")

        self.stdout.write(f"Meng-encode {len(entri)} entri…")
        penguji = sim.siapkan_penguji(engine, entri)
        ringkasan = [("Entri (pertanyaan + variasi)", len(entri)),
                     ("FAQ", len(set(e["faq_id"] for e in entri)))]

        rawan = []
        if not opts["tanpa_variasi"]:
            akurasi, rawan = sim.uji_variasi(penguji, entri)
            ringkasan += [("Uji variasi: akurasi", round(akurasi, 4)),
                          ("Uji variasi: rawan direbut", len(rawan))]
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nUji variasi: {akurasi:.3f} — {len(rawan)} rawan direbut FAQ lain"))
            for r in rawan[:TAMPIL_MAKS]:
                self.stdout.write(
                    f"  {r['skor_dapat']:.3f} '{r['teks'][:55]}'\n"
                    f"        milik  : {r['milik'][:70]}\n"
                    f"        direbut: {r['dapat'][:70]}")

        daftar = []
        hard = muat_hard_eval(settings.ARTIFACTS_DIR / "hard_eval.json") or {}
        daftar += [(q, k) for k, qs in hard.items() for q in qs]
        for b in opts["berkas"]:
            try:
                daftar += sim.baca_berkas(b)
            except (OSError, ValueError) as e:
                raise CommandError(f"Gagal membaca {b}: {e}") from e
        if opts["log_hari"] > 0:
            from percakapan.admin import FILTER_GAGAL
            from percakapan.models import ChatLog
            batas = timezone.now() - timedelta(days=opts["log_hari"])
            log_q = (ChatLog.objects.filter(FILTER_GAGAL, dibuat__gte=batas)
                     .values_list("query", flat=True).distinct())
            daftar += [(q, None) for q in log_q]

        hasil = sim.uji_pertanyaan(penguji, daftar) if daftar else []
        if hasil:
            dinilai = [h for h in hasil if h["benar"] is not None]
            benar = sum(1 for h in dinilai if h["benar"])
            per_tipe = {}
            for h in hasil:
                per_tipe[h["tipe"]] = per_tipe.get(h["tipe"], 0) + 1
            ringkasan.append(("Uji pertanyaan: jumlah", len(hasil)))
            ringkasan += [(f"Uji pertanyaan: {t}", n) for t, n in sorted(per_tipe.items())]
            if dinilai:
                ringkasan.append(("Uji pertanyaan: benar (yang punya harapan)",
                                  f"{benar}/{len(dinilai)}"))
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\nUji pertanyaan: {len(hasil)} — "
                + ", ".join(f"{t} {n}" for t, n in sorted(per_tipe.items()))
                + (f"; benar {benar}/{len(dinilai)}" if dinilai else "")))
            salah = [h for h in hasil if h["benar"] is False
                     or (h["benar"] is None and h["tipe"] != "jawaban")]
            for h in salah[:TAMPIL_MAKS]:
                self.stdout.write(
                    f"  {h['tipe']:<11} {h['skor']:.3f} '{h['pertanyaan'][:55]}'"
                    + (f"\n        dapat  : {h['terpilih'][:70]}" if h["terpilih"] else "")
                    + (f"\n        harapan: {h['harapan'][:70]}" if h["harapan"] else ""))

        if opts["keluar"]:
            sim.tulis_laporan(opts["keluar"], ringkasan, rawan, hasil)
            self.stdout.write(self.style.SUCCESS(f"\nLaporan: {opts['keluar']}"))
