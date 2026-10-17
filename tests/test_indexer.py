"""Tes indexer & regression gate — tanpa Django, tanpa DB."""

import numpy as np
import pytest

from retrieval.engine import Engine, Snapshot
from retrieval.indexer import (bangun_dan_uji, bangun_snapshot, dari_bytes,
                               evaluasi, ke_bytes)
from tests.test_engine import ModelTiruan

ENTRI = [
    {"faq_id": 1, "teks": "apa itu universitas bangka belitung"},
    {"faq_id": 1, "teks": "ubb itu kampus apa"},                  # variasi
    {"faq_id": 2, "teks": "berapa uang kuliah tunggal"},
    {"faq_id": 3, "teks": "kapan pendaftaran dibuka"},
]


def engine_kosong():
    return Engine(ModelTiruan(), None)


def test_bangun_snapshot():
    snap = bangun_snapshot(engine_kosong(), ENTRI, versi=7)
    assert snap.versi == 7
    assert snap.jumlah_vektor == 4
    assert snap.pemilik == [1, 1, 2, 3]
    assert snap.dim == ModelTiruan.DIM


def test_snapshot_vektor_dinormalisasi():
    snap = bangun_snapshot(engine_kosong(), ENTRI, versi=1)
    norma = np.linalg.norm(snap.vektor, axis=1)
    assert np.allclose(norma, 1.0, atol=1e-5)


def test_entri_kosong_ditolak():
    with pytest.raises(ValueError):
        bangun_snapshot(engine_kosong(), [], versi=1)


def test_variasi_menunjuk_faq_yang_sama():
    snap = bangun_snapshot(engine_kosong(), ENTRI, versi=1)
    assert len(set(snap.pemilik)) == 3       # 4 vektor, 3 jawaban


# --- serialisasi BinaryField --------------------------------------------

def test_roundtrip_bytes():
    snap = bangun_snapshot(engine_kosong(), ENTRI, versi=1)
    pulih = dari_bytes(ke_bytes(snap.vektor), snap.dim)
    assert pulih.shape == snap.vektor.shape
    assert np.allclose(pulih, snap.vektor)


def test_bytes_float32():
    """Konsistensi dtype penting: index dibaca ulang di proses lain."""
    snap = bangun_snapshot(engine_kosong(), ENTRI, versi=1)
    assert len(ke_bytes(snap.vektor)) == snap.jumlah_vektor * snap.dim * 4


# --- regression gate -----------------------------------------------------

PETA = {"apa itu universitas bangka belitung": 1,
        "berapa uang kuliah tunggal": 2,
        "kapan pendaftaran dibuka": 3}


def test_evaluasi_sempurna():
    e = engine_kosong()
    snap = bangun_snapshot(e, ENTRI, versi=1)
    hard = {"apa itu universitas bangka belitung": ["apa itu universitas bangka belitung"]}
    acc, gagal = evaluasi(e, snap, hard, PETA)
    assert acc == 1.0 and gagal == []


def test_evaluasi_menangkap_kegagalan():
    e = engine_kosong()
    snap = bangun_snapshot(e, ENTRI, versi=1)
    # Parafrase yang justru mengarah ke FAQ lain
    hard = {"apa itu universitas bangka belitung": ["berapa uang kuliah tunggal"]}
    acc, gagal = evaluasi(e, snap, hard, PETA)
    assert acc == 0.0
    assert gagal[0]["dapat_faq_id"] == 2


def test_hard_eval_menyebut_pertanyaan_tak_dikenal_dilewati():
    e = engine_kosong()
    snap = bangun_snapshot(e, ENTRI, versi=1)
    acc, gagal = evaluasi(e, snap, {"pertanyaan yang tidak ada": ["apa pun"]}, PETA)
    assert acc == 0.0 and gagal == []      # dilewati, bukan dihitung salah


def test_gate_menolak_index_buruk():
    e = engine_kosong()
    hard = {"apa itu universitas bangka belitung": ["berapa uang kuliah tunggal"]}
    hasil = bangun_dan_uji(e, ENTRI, 2, hard, PETA, ambang=0.85)
    assert hasil.lolos is False
    assert "DITOLAK" in hasil.catatan


def test_gate_meloloskan_index_baik():
    e = engine_kosong()
    hard = {"apa itu universitas bangka belitung": ["apa itu universitas bangka belitung"]}
    hasil = bangun_dan_uji(e, ENTRI, 2, hard, PETA, ambang=0.85)
    assert hasil.lolos is True
    assert hasil.acc_at_1 == 1.0


def test_tanpa_hard_eval_gate_dilewati_dengan_catatan_jelas():
    """Bagian 9.4 — admin tidak boleh mengira terlindungi padahal belum."""
    hasil = bangun_dan_uji(engine_kosong(), ENTRI, 2, hard_eval=None)
    assert hasil.lolos is True
    assert hasil.acc_at_1 is None
    assert "DILEWATI" in hasil.catatan


def test_evaluasi_tidak_menyentuh_index_aktif():
    """Uji memakai snapshot KANDIDAT, bukan yang sedang melayani."""
    e = engine_kosong()
    aktif = bangun_snapshot(e, ENTRI[:1], versi=1)
    e.pasang_snapshot(aktif)
    kandidat = bangun_snapshot(e, ENTRI, versi=2)
    evaluasi(e, kandidat, {"apa itu universitas bangka belitung": ["apa itu ubb"]}, PETA)
    assert e.snapshot.versi == 1             # tidak tertukar
    assert e.snapshot.jumlah_vektor == 1


def test_jumlah_answer_dihitung_unik():
    hasil = bangun_dan_uji(engine_kosong(), ENTRI, 1)
    assert hasil.jumlah_answer == 3
    assert hasil.snapshot.jumlah_vektor == 4
