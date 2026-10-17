"""Tes kamus sinonim domain untuk augmentasi data latih.

Kamus ini menyasar 23 kasus hard eval yang jawaban benarnya tidak muncul di
top-5 — bukan salah peringkat, tapi konsepnya belum dikenali model. Tes di
sini menjaga cakupannya tidak menyusut diam-diam saat kamus disunting.
"""

import pathlib
import re
import sys

import pytest

NOTEBOOK = pathlib.Path(__file__).resolve().parent.parent / "notebook"
sys.path.insert(0, str(NOTEBOOK))

from sinonim_domain import (KE_RESMI, SINONIM_DOMAIN, augment_sinonim,
                            pasangan_sinonim_global)

# Query hard eval yang gagal — disalin apa adanya dari pengukuran nyata.
KASUS_GAGAL = [
    "jalur yang pakai utbk maksudnya gimana",
    "kalau gagal utbk masih bisa masuk lewat seleksi kampus sendiri",
    "bantuan dana kuliah yang bisa diambil apa aja",
    "keringanan biaya buat yang kurang mampu ada?",
    "ada tempat tinggal buat anak rantau gak",
    "sewa kamar di dalam kampus harganya berapa",
    "makan siang bisa di mana kalau di kampus",
    "ukm sama bem apa aja yang bisa diikuti",
    "bisa kerja praktek di perusahaan gak",
    "durasi kerja praktek berapa bulan",
    "biar bisa ikut prosesi kelulusan harus memenuhi apa",
    "lulusan sini gampang dapat pekerjaan gak",
    "orang luar negeri boleh kuliah di sini",
    "bisa kuliah sementara di kampus lain gak",
    "teman saya pakai kursi roda, kampusnya bisa diakses",
    "ada antar jemput ke kampus",
    "bisa lanjut doktor di sini",
    "program diploma tersedia gak",
    "kalau mau belajar konstruksi bangunan masuk prodi mana",
    "budidaya ikan ada jurusannya",
    "minat di bidang pertanian masuk prodi mana",
    "nilai mutu kampus ini dari ban-pt apa",
    "cek peringkat mutu prodi lewat mana",
]


@pytest.mark.parametrize("query", KASUS_GAGAL)
def test_setiap_kasus_gagal_tercakup(query):
    """Kamus harus mengenali minimal satu sinonim di tiap query yang gagal."""
    ql = query.lower()
    cocok = [i for i in KE_RESMI
             if re.search(rf"\b{re.escape(i)}\b", ql)]
    assert cocok, (
        f"{query!r} tidak tersentuh kamus — kasus ini akan tetap gagal "
        f"setelah fine-tuning ulang")


def test_kamus_tidak_menyusut():
    """Menangkap penghapusan entri yang tidak disengaja saat menyunting."""
    assert len(SINONIM_DOMAIN) >= 33
    assert sum(len(v) for v in SINONIM_DOMAIN.values()) >= 113


def test_augment_menghasilkan_varian_berbeda():
    hasil = augment_sinonim("Apakah ada program magang?", n=4, seed=1)
    assert hasil
    gabung = " ".join(hasil)
    # "magang" harus tergantikan bahasa camaba
    assert "kerja praktek" in gabung or "pkl" in gabung


def test_augment_tidak_mengembalikan_pertanyaan_asli():
    asli = "apakah tersedia asrama"
    assert asli not in augment_sinonim("Apakah tersedia asrama?", seed=1)


def test_augment_pertanyaan_tanpa_sinonim_aman():
    """Pertanyaan yang tidak memuat istilah kamus tidak boleh error."""
    assert augment_sinonim("Siapa rektor saat ini?", seed=1) == []


def test_pasangan_global_simetris_dan_tidak_kosong():
    pasangan = pasangan_sinonim_global()
    assert len(pasangan) >= 400
    # tiap pasangan berisi dua teks berbeda
    assert all(a != b for a, b in pasangan)


def test_tidak_ada_sinonim_duplikat_lintas_istilah():
    """Satu frasa camaba tidak boleh memetakan ke dua istilah resmi berbeda —
    itu justru menciptakan ambiguitas baru saat pelatihan."""
    terlihat = {}
    bentrok = []
    for resmi, daftar in SINONIM_DOMAIN.items():
        for informal in daftar:
            if informal in terlihat and terlihat[informal] != resmi:
                bentrok.append((informal, terlihat[informal], resmi))
            terlihat[informal] = resmi
    assert not bentrok, f"sinonim bentrok: {bentrok}"
