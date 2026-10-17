"""Uji chatbot dari terminal — sekali tanya atau mode interaktif.

Dipakai untuk pengujian manual Fase 0, sebelum API (Fase 2) ada.

    python manage.py tanya "berapa ukt"      # sekali jalan
    python manage.py tanya                   # mode interaktif
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from faq.models import Faq, IndexVersion

WARNA = {
    "jawaban": "\033[92m", "sapaan": "\033[96m", "klarifikasi": "\033[93m",
    "eskalasi": "\033[95m", "fallback": "\033[91m", "kosong": "\033[90m",
}
RESET = "\033[0m"
ABU = "\033[90m"


class Command(BaseCommand):
    help = "Uji retrieval dari terminal (sekali tanya atau interaktif)."

    def add_arguments(self, parser):
        parser.add_argument("pertanyaan", nargs="*",
                            help="Pertanyaan. Kosongkan untuk mode interaktif.")
        parser.add_argument("--detail", action="store_true",
                            help="Tampilkan kandidat teratas beserta skornya")

    # --- penyiapan -------------------------------------------------------

    def _siapkan(self):
        from retrieval.engine import (Snapshot, get_engine, muat_engine_global)
        from retrieval.indexer import dari_bytes

        engine = get_engine() or muat_engine_global(settings.ARTIFACTS_DIR)
        if engine is None:
            raise CommandError(
                f"Model tidak ada di {settings.ARTIFACTS_DIR}/model/. "
                "Jalankan: python manage.py siapkan_model")

        iv = IndexVersion.objects.filter(aktif=True).first()
        if iv is None:
            raise CommandError(
                "Belum ada index aktif. Jalankan: python manage.py reindex --paksa")

        engine.pasang_snapshot(Snapshot(
            iv.versi, dari_bytes(bytes(iv.vektor), iv.dim), iv.pemilik, iv.dim))
        return engine, iv

    @staticmethod
    def _metadata(ids):
        keluar = {}
        for f in Faq.objects.filter(id__in=ids):
            keluar[f.id] = dict(
                pertanyaan=f.pertanyaan, jawaban=f.jawaban, kategori=f.kategori,
                sumber_label=f.sumber_label, sumber_url=f.sumber_url,
                butuh_verifikasi=f.butuh_verifikasi,
                terakhir_diverifikasi=(f.terakhir_diverifikasi.isoformat()
                                       if f.terakhir_diverifikasi else None))
        return keluar

    # --- tampilan --------------------------------------------------------

    def _tampilkan(self, engine, query, detail):
        hasil = engine.jawab(query, self._metadata)
        warna = WARNA.get(str(hasil.tipe), "")

        self.stdout.write(f"\n{warna}┌─ {str(hasil.tipe).upper()}{RESET} "
                          f"{ABU}skor {hasil.skor:.4f}{RESET}")
        for baris in hasil.jawaban.splitlines():
            self.stdout.write(f"{warna}│{RESET} {baris}")

        if hasil.matched:
            self.stdout.write(f"{ABU}│ cocok dengan: [{hasil.faq_id}] "
                              f"{hasil.matched}{RESET}")
        if detail and hasil.kandidat:
            self.stdout.write(f"{ABU}│ kandidat:{RESET}")
            for k in hasil.kandidat:
                self.stdout.write(f"{ABU}│   {k['skor']:.4f}  [{k['id']}] "
                                  f"{k['pertanyaan'][:60]}{RESET}")
        self.stdout.write(f"{warna}└─{RESET}")

    # --- masuk -----------------------------------------------------------

    def handle(self, *args, **opts):
        engine, iv = self._siapkan()

        if opts["pertanyaan"]:
            self._tampilkan(engine, " ".join(opts["pertanyaan"]), opts["detail"])
            return

        self.stdout.write(
            f"\nChatbot PMB UBB — index v{iv.versi} "
            f"({iv.jumlah_vektor} vektor, {iv.jumlah_answer} jawaban)\n"
            f"tau_high={engine.tau_high}  tau_low={engine.tau_low}\n"
            f"{ABU}Ketik pertanyaan. 'keluar' untuk selesai.{RESET}")

        while True:
            try:
                q = input("\n\033[1mcamaba>\033[0m ").strip()
            except (EOFError, KeyboardInterrupt):
                self.stdout.write("\nSelesai.")
                return
            if q.lower() in {"keluar", "exit", "quit", "q"}:
                self.stdout.write("Selesai.")
                return
            if q:
                self._tampilkan(engine, q, opts["detail"])
