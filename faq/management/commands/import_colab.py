"""Artefak notebook -> basis data.

Menerima dua bentuk masukan:
  1. knowledge_base.json  — keluaran `df.to_json(orient="records")` di notebook
  2. Excel panitia PMB    — diparse dengan parser YANG SAMA seperti notebook

Parser Excel dan aturan flag `butuh_verifikasi` disalin dari notebook (sel 2
dan 3b) supaya isi basis data identik dengan yang dipakai saat melatih model.
"""

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from faq.models import Faq, FaqVariasi

# --- disalin dari notebook, sel 2 ----------------------------------------
KATEGORI_RE = re.compile(r"^[A-Z]{1,2}\.\s+\S")
HEADER_TOKENS = {"no", "pertanyaan", "jawaban", "sumber"}

# --- disalin dari notebook, sel 3b ---------------------------------------
PLACEHOLDER_PAT = r"perlu wawancara|belum ditemukan informasi|tidak ditemukan informasi"


def parse_faq_excel(path, sheet=0):
    """Parser stateful untuk Excel FAQ berstruktur seksi.

    Mengembalikan (list_of_dict, list_of_warnings).
    """
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[sheet]] if isinstance(sheet, int) else wb[sheet]

    rows, warns = [], []
    kategori, sub_kategori = None, None

    for i, raw in enumerate(ws.iter_rows(values_only=True), start=1):
        cells = [("" if c is None else str(c).strip()) for c in raw]
        cells += [""] * (4 - len(cells))          # pastikan minimal 4 kolom
        no, pertanyaan, jawaban, sumber = cells[:4]

        if not any(cells):                        # baris pemisah kosong
            continue

        # Baris judul: hanya kolom A yang terisi
        if no and not pertanyaan and not jawaban:
            if KATEGORI_RE.match(no):
                kategori, sub_kategori = no, None
            else:
                sub_kategori = no
            continue

        # Baris header tabel yang berulang di tiap seksi
        if no.lower() in HEADER_TOKENS and pertanyaan.lower() in HEADER_TOKENS:
            continue

        if pertanyaan and jawaban:
            rows.append({
                "kategori":     kategori or "(tanpa kategori)",
                "sub_kategori": sub_kategori or "",
                "pertanyaan":   " ".join(pertanyaan.split()),
                "jawaban":      " ".join(jawaban.split()),
                "sumber":       " ".join(sumber.split()),
                "baris_excel":  i,
            })
        elif pertanyaan and not jawaban:
            warns.append(f"Baris {i}: pertanyaan tanpa jawaban -> {pertanyaan[:70]!r}")
        elif jawaban and not pertanyaan:
            warns.append(f"Baris {i}: jawaban tanpa pertanyaan -> {jawaban[:70]!r}")

    return rows, warns


def flag_butuh_verifikasi(jawaban: str) -> bool:
    """Aturan notebook sel 3b — jawaban placeholder tidak boleh tampil."""
    return bool(re.search(PLACEHOLDER_PAT, (jawaban or "").lower()))


def _pisah_sumber(sumber: str) -> tuple[str, str]:
    """Kolom 'sumber' Excel bisa berisi URL atau label bebas."""
    s = (sumber or "").strip()
    if s in {"", "—", "-"}:
        return "", ""
    m = re.search(r"https?://\S+", s)
    if m:
        url = m.group(0).rstrip(").,;")
        label = s.replace(m.group(0), "").strip(" -–—:()")
        return label[:200], url
    return s[:200], ""


class Command(BaseCommand):
    help = "Impor knowledge_base.json atau Excel panitia PMB ke tabel Faq."

    def add_arguments(self, parser):
        parser.add_argument("sumber", help="Path ke knowledge_base.json atau .xlsx")
        parser.add_argument("--sheet", default=0,
                            help="Nama atau indeks sheet (khusus Excel)")
        parser.add_argument("--hapus-dulu", action="store_true",
                            help="Kosongkan tabel Faq sebelum impor")
        parser.add_argument("--dry-run", action="store_true",
                            help="Tampilkan ringkasan tanpa menulis ke basis data")

    def handle(self, *args, **opts):
        path = Path(opts["sumber"])
        if not path.exists():
            raise CommandError(f"Berkas tidak ditemukan: {path}")

        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            sheet = opts["sheet"]
            try:
                sheet = int(sheet)
            except (TypeError, ValueError):
                pass
            baris, warns = parse_faq_excel(path, sheet)
            for w in warns[:10]:
                self.stderr.write(self.style.WARNING(f"  ⚠️  {w}"))
            if len(warns) > 10:
                self.stderr.write(self.style.WARNING(
                    f"  ... dan {len(warns) - 10} peringatan lain"))
        elif path.suffix.lower() == ".json":
            try:
                with open(path, encoding="utf-8") as f:
                    baris = json.load(f)
            except json.JSONDecodeError as e:
                raise CommandError(f"{path} bukan JSON yang sah: {e}")

            # Bentuk yang diharapkan: list of dict, keluaran backup_kb atau
            # df.to_json(orient="records") di notebook.
            if isinstance(baris, dict):
                raise CommandError(
                    f"{path} berisi objek JSON, bukan daftar. Berkas yang "
                    "benar diawali '[' dan berisi daftar FAQ — periksa apakah "
                    "isinya terbungkus kunci lain.")
            if not isinstance(baris, list):
                raise CommandError(
                    f"{path} berisi {type(baris).__name__}, seharusnya daftar FAQ.")
        else:
            raise CommandError(f"Format tidak dikenali: {path.suffix}")

        if not baris:
            ukuran = path.stat().st_size
            raise CommandError(
                f"{path} tidak berisi satu pun FAQ (ukuran {ukuran} byte).\n"
                "Kemungkinan berkas ini hasil ekspor dari basis data yang masih "
                "kosong. Ekspor ulang dari mesin yang datanya lengkap:\n"
                "  python manage.py backup_kb --keluar kb-awal.json\n"
                "atau impor langsung dari Excel panitia PMB.")

        # Deduplikasi berdasarkan teks pertanyaan (Bagian 7.2: entri kembar
        # membuat retrieval ambigu selamanya).
        terlihat: dict[str, dict] = {}
        kembar = []
        for r in baris:
            kunci = " ".join(str(r.get("pertanyaan", "")).lower().split())
            if not kunci:
                continue
            if kunci in terlihat:
                kembar.append(r["pertanyaan"])
                continue
            terlihat[kunci] = r

        n_flag = sum(1 for r in terlihat.values()
                     if flag_butuh_verifikasi(r.get("jawaban", "")))

        self.stdout.write(f"Baris terparsing   : {len(baris)}")
        self.stdout.write(f"Unik               : {len(terlihat)}")
        self.stdout.write(f"Kembar dilewati    : {len(kembar)}")
        self.stdout.write(f"Butuh verifikasi   : {n_flag} "
                          f"({n_flag / len(terlihat):.1%})")
        for k in kembar[:5]:
            self.stdout.write(self.style.WARNING(f"  ⚠️  kembar: {k[:70]}"))

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("\n--dry-run: tidak ada yang ditulis."))
            return

        with transaction.atomic():
            if opts["hapus_dulu"]:
                n = Faq.objects.count()
                Faq.objects.all().delete()
                self.stdout.write(self.style.WARNING(f"{n} entri lama dihapus."))

            dibuat = diperbarui = 0
            for r in terlihat.values():
                label, url = _pisah_sumber(r.get("sumber", ""))
                nilai = {
                    "jawaban": r.get("jawaban", ""),
                    "kategori": r.get("kategori", "") or "",
                    "sub_kategori": r.get("sub_kategori", "") or "",
                    "sumber_label": label,
                    "sumber_url": url,
                    "butuh_verifikasi": flag_butuh_verifikasi(r.get("jawaban", "")),
                }
                obj, baru = Faq.objects.update_or_create(
                    pertanyaan=r["pertanyaan"], defaults=nilai)
                dibuat += baru
                diperbarui += not baru

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ {dibuat} dibuat, {diperbarui} diperbarui. "
            f"Total FAQ: {Faq.objects.count()}, "
            f"variasi: {FaqVariasi.objects.count()}"))
        self.stdout.write(
            "Catatan: entri butuh_verifikasi TETAP masuk index; jawabannya "
            "diganti pesan eskalasi saat runtime (prinsip #4).")
