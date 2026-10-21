"""Tes import_colab — aturan flag & dedup harus persis seperti notebook."""

import json

import pytest
from django.core.management import call_command

from faq.management.commands.import_colab import (_pisah_sumber,
                                                  flag_butuh_verifikasi)
from faq.models import Faq

pytestmark = pytest.mark.django_db


# --- aturan flag (notebook sel 3b) — murni, tanpa DB ---------------------

@pytest.mark.parametrize("jawaban", [
    "Perlu wawancara.",
    "PERLU WAWANCARA dengan bagian akademik",
    "Belum ditemukan informasi resmi",
    "Tidak ditemukan informasi di website",
    "Perlu wawancara. (Tidak ditemukan angka resmi.)",
])
def test_placeholder_ditandai(jawaban):
    assert flag_butuh_verifikasi(jawaban) is True


@pytest.mark.parametrize("jawaban", [
    "UBB adalah PTN di Bangka Belitung.",
    "Pendaftaran dibuka 1 Februari 2026.",
    "",
])
def test_jawaban_final_tidak_ditandai(jawaban):
    assert flag_butuh_verifikasi(jawaban) is False


def test_flag_aman_untuk_none():
    assert flag_butuh_verifikasi(None) is False


# --- pemisahan sumber ----------------------------------------------------

@pytest.mark.parametrize("masukan,label,url", [
    ("https://ubb.ac.id", "", "https://ubb.ac.id"),
    ("Profil UBB", "Profil UBB", ""),
    ("—", "", ""),
    ("-", "", ""),
    ("", "", ""),
    ("Web PMB (https://pmb.ubb.ac.id)", "Web PMB", "https://pmb.ubb.ac.id"),
])
def test_pisah_sumber(masukan, label, url):
    assert _pisah_sumber(masukan) == (label, url)


# --- impor JSON ----------------------------------------------------------

def tulis_kb(tmp_path, baris):
    p = tmp_path / "knowledge_base.json"
    p.write_text(json.dumps(baris, ensure_ascii=False), encoding="utf-8")
    return p


def test_impor_json(tmp_path):
    p = tulis_kb(tmp_path, [
        {"pertanyaan": "Apa itu UBB?", "jawaban": "PTN di Babel.",
         "kategori": "A. Umum", "sumber": "https://ubb.ac.id"},
        {"pertanyaan": "Berapa luas kampus?", "jawaban": "Perlu wawancara.",
         "kategori": "A. Umum", "sumber": "—"},
    ])
    call_command("import_colab", str(p))

    assert Faq.objects.count() == 2
    a = Faq.objects.get(pertanyaan="Apa itu UBB?")
    assert a.butuh_verifikasi is False
    assert a.sumber_url == "https://ubb.ac.id"

    b = Faq.objects.get(pertanyaan="Berapa luas kampus?")
    assert b.butuh_verifikasi is True
    assert b.sumber == ""


def test_dedup_pertanyaan_kembar(tmp_path):
    """Entri kembar membuat retrieval ambigu selamanya (Bagian 7.2)."""
    p = tulis_kb(tmp_path, [
        {"pertanyaan": "Kapan pendaftaran dibuka?", "jawaban": "Februari."},
        {"pertanyaan": "kapan  pendaftaran   dibuka?", "jawaban": "Maret."},
    ])
    call_command("import_colab", str(p))
    assert Faq.objects.count() == 1


def test_dry_run_tidak_menulis(tmp_path):
    p = tulis_kb(tmp_path, [{"pertanyaan": "Apa itu UBB?", "jawaban": "PTN."}])
    call_command("import_colab", str(p), "--dry-run")
    assert Faq.objects.count() == 0


def test_impor_ulang_memperbarui_bukan_menggandakan(tmp_path):
    p1 = tulis_kb(tmp_path, [{"pertanyaan": "Apa itu UBB?", "jawaban": "Versi lama."}])
    call_command("import_colab", str(p1))
    p2 = tmp_path / "kb2.json"
    p2.write_text(json.dumps([{"pertanyaan": "Apa itu UBB?", "jawaban": "Versi baru."}]),
                  encoding="utf-8")
    call_command("import_colab", str(p2))

    assert Faq.objects.count() == 1
    assert Faq.objects.first().jawaban == "Versi baru."


def test_berkas_tidak_ada_error_jelas(tmp_path):
    from django.core.management.base import CommandError
    with pytest.raises(CommandError, match="tidak ditemukan"):
        call_command("import_colab", str(tmp_path / "hantu.json"))


def test_format_tidak_dikenali(tmp_path):
    from django.core.management.base import CommandError
    p = tmp_path / "data.txt"
    p.write_text("bukan json")
    with pytest.raises(CommandError, match="tidak dikenali"):
        call_command("import_colab", str(p))


# --- pesan galat yang menuntun -------------------------------------------

def test_json_kosong_menjelaskan_penyebab(tmp_path):
    """Gejala nyata di VPS: backup_kb dijalankan sebelum ada data."""
    from django.core.management.base import CommandError

    p = tmp_path / "kb-awal.json"
    p.write_text("[]", encoding="utf-8")

    with pytest.raises(CommandError) as e:
        call_command("import_colab", str(p))
    pesan = str(e.value)
    assert "tidak berisi satu pun FAQ" in pesan
    assert "backup_kb" in pesan          # beri jalan keluar, jangan cuma menolak


def test_json_berupa_objek_ditolak_dengan_jelas(tmp_path):
    from django.core.management.base import CommandError

    p = tmp_path / "kb.json"
    p.write_text('{"faq": [{"pertanyaan": "a", "jawaban": "b"}]}',
                 encoding="utf-8")

    with pytest.raises(CommandError, match="objek JSON, bukan daftar"):
        call_command("import_colab", str(p))


def test_json_rusak_ditolak_dengan_jelas(tmp_path):
    from django.core.management.base import CommandError

    p = tmp_path / "kb.json"
    p.write_text("{ini bukan json", encoding="utf-8")

    with pytest.raises(CommandError, match="bukan JSON yang sah"):
        call_command("import_colab", str(p))


# --- variasi cara bertanya -------------------------------------------------

def tulis_excel(tmp_path, variasi):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "FAQ"
    ws.append(["A. Informasi Umum"])
    ws.append(["No", "Pertanyaan", "Jawaban", "Sumber"])
    ws.append([1, "Apa itu UBB?", "PTN di Babel.", "Profil UBB"])
    ws.append([2, "Berapa UKT UBB?", "Sesuai kelompok UKT.", "—"])
    vs = wb.create_sheet("Variasi")
    vs.append(["No", "Kategori", "Pertanyaan utama", "Variasi"])
    for baris in variasi:
        vs.append(baris)
    p = tmp_path / "faq.xlsx"
    wb.save(p)
    return p


def test_impor_excel_dengan_sheet_variasi(tmp_path):
    from faq.models import FaqVariasi

    p = tulis_excel(tmp_path, [
        [1, "A", "Apa itu UBB?", "ubb itu apa"],
        [1, "A", "apa itu  ubb?", "Universitas Bangka Belitung itu kampus apa?"],
        [1, "A", "Apa itu UBB?", "Apa itu UBB?"],          # sama dgn pertanyaan
        [2, "A", "Berapa UKT UBB?", "ukt ubb brp"],
        [None, None, None, None],
    ])
    call_command("import_colab", str(p))

    assert Faq.objects.count() == 2
    ubb = Faq.objects.get(pertanyaan="Apa itu UBB?")
    assert set(ubb.variasi.values_list("teks", flat=True)) == {
        "ubb itu apa", "Universitas Bangka Belitung itu kampus apa?"}
    assert FaqVariasi.objects.count() == 3


def test_impor_ulang_variasi_tidak_menggandakan(tmp_path):
    from faq.models import FaqVariasi

    p = tulis_excel(tmp_path, [[1, "A", "Apa itu UBB?", "ubb itu apa"]])
    call_command("import_colab", str(p))
    call_command("import_colab", str(p))
    assert FaqVariasi.objects.count() == 1


def test_variasi_tanpa_faq_dilewati(tmp_path, capsys):
    from faq.models import FaqVariasi

    p = tulis_excel(tmp_path, [[9, "A", "Pertanyaan yang tidak ada?", "x"]])
    call_command("import_colab", str(p))
    assert FaqVariasi.objects.count() == 0
    assert "variasi tanpa FAQ" in capsys.readouterr().err


def test_dry_run_tidak_menulis_variasi(tmp_path):
    from faq.models import FaqVariasi

    p = tulis_excel(tmp_path, [[1, "A", "Apa itu UBB?", "ubb itu apa"]])
    call_command("import_colab", str(p), "--dry-run")
    assert FaqVariasi.objects.count() == 0


def test_impor_json_backup_kb_membawa_variasi(tmp_path):
    """Keluaran backup_kb menyimpan variasi; impor ulang tidak boleh membuangnya."""
    p = tulis_kb(tmp_path, [
        {"pertanyaan": "Apa itu UBB?", "jawaban": "PTN di Babel.",
         "variasi": ["ubb itu apa", "Apa sih UBB?"]},
    ])
    call_command("import_colab", str(p))
    assert Faq.objects.get().variasi.count() == 2


def test_hapus_dulu_memulihkan_variasi_log_dan_sinkron(tmp_path):
    """Variasi dari tombol Tautkan dan paket sinkron tidak ada di Excel."""
    from faq.models import FaqVariasi
    p = tulis_kb(tmp_path, [{"pertanyaan": "Apa itu UBB?", "jawaban": "PTN."},
                            {"pertanyaan": "Dibuang?", "jawaban": "Ya."}])
    call_command("import_colab", str(p))
    ubb = Faq.objects.get(pertanyaan="Apa itu UBB?")
    FaqVariasi.objects.create(faq=ubb, teks="ubb itu apa", asal="log")
    FaqVariasi.objects.create(faq=ubb, teks="ubb kampus apa", asal="augmentasi")
    FaqVariasi.objects.create(faq=ubb, teks="variasi admin lama", asal="admin")
    FaqVariasi.objects.create(faq=Faq.objects.get(pertanyaan="Dibuang?"),
                              teks="ikut terbuang", asal="log")

    p2 = tmp_path / "kb2.json"
    p2.write_text(json.dumps([{"pertanyaan": "Apa itu UBB?", "jawaban": "PTN baru."}]),
                  encoding="utf-8")
    call_command("import_colab", str(p2), "--hapus-dulu")

    ubb = Faq.objects.get()
    assert dict(ubb.variasi.values_list("teks", "asal")) == {
        "ubb itu apa": "log", "ubb kampus apa": "augmentasi"}
