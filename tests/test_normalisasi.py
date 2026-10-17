"""Pagar pengaman retrieval/text.py.

Kalau tes ini merah, JANGAN deploy. Artinya normalisasi runtime sudah
menyimpang dari normalisasi yang dipakai saat membangun index di notebook,
dan akurasi akan turun tanpa satu pun error muncul.

Tes ini sengaja TIDAK mengimpor Django — retrieval/ harus bisa diuji polos.
"""
import json
import pathlib

import pytest

from retrieval.text import SINGKATAN, SLANG, normalize

GOLD = pathlib.Path(__file__).resolve().parent.parent / "artifacts" / "normalisasi_gold.json"


def _muat():
    with open(GOLD, encoding="utf-8") as f:
        return json.load(f)


def test_gold_file_ada():
    assert GOLD.exists(), (
        f"{GOLD} tidak ada. Bangkitkan ulang dari notebook sebelum menjalankan tes."
    )


@pytest.mark.parametrize("masukan,harapan", _muat()["expand_true"])
def test_normalisasi_sesuai_notebook(masukan, harapan):
    assert normalize(masukan) == harapan


@pytest.mark.parametrize("masukan,harapan", _muat()["expand_false"])
def test_normalisasi_tanpa_expand_sesuai_notebook(masukan, harapan):
    assert normalize(masukan, expand=False) == harapan


# --- Sifat yang harus dipegang, di luar kasus gold ------------------------

def test_idempoten():
    """normalize(normalize(x)) == normalize(x).

    Penting karena teks yang sudah ternormalisasi kadang lewat lagi
    (mis. variasi yang disimpan admin lalu di-index ulang).
    """
    for s in ["Min, brp UKT fak teknik yg S1?", "apa itu UBB", "gimana caranya"]:
        sekali = normalize(s)
        assert normalize(sekali) == sekali


def test_tanda_tanya_dipertahankan():
    """'?' adalah sinyal intent — notebook sengaja tidak membuangnya."""
    assert "?" in normalize("apa itu ubb?")


def test_url_dibuang():
    assert "http" not in normalize("cek https://ubb.ac.id ya")


def test_tidak_pernah_none_atau_error():
    for s in [None, "", "   ", 0, 3.14, "!!!"]:
        assert isinstance(normalize(s), str)


def test_word_boundary_dihormati():
    """Pola singkatan/slang harus \\b — 'ubbi' tidak boleh jadi 'universitas...i'."""
    assert "universitas bangka belitung" not in normalize("ubbi")
    assert normalize("tikus") == "tikus"          # 'ti' di tengah kata


def test_kamus_tidak_kosong():
    """Menangkap kasus file ter-truncate saat edit."""
    assert len(SINGKATAN) == 10
    assert len(SLANG) == 17
