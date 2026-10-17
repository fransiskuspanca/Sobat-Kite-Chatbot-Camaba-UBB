"""Tes engine dengan model tiruan.

Tidak memuat bobot 600 MB dan tidak menyentuh Django — inilah bukti bahwa
retrieval/ benar-benar terisolasi (Bagian 5 dokumen rencana).
"""

import hashlib

import numpy as np
import pytest

from retrieval.engine import Engine, Snapshot
from retrieval.tiers import Tipe


class ModelTiruan:
    """Encoder deterministik: bag-of-words yang dihash lalu dinormalisasi.

    Cukup untuk menguji aljabar pencarian; tidak mengukur kualitas semantik.

    Memakai blake2b, BUKAN hash() bawaan Python: nilai hash() untuk str
    diacak ulang tiap proses (PYTHONHASHSEED), sehingga skor kemiripan
    berubah-ubah antar-run dan membuat tes flaky — query di luar domain
    sesekali bertabrakan hash dengan FAQ dan lolos ambang.
    """
    DIM = 32

    @staticmethod
    def _slot(kata: str) -> int:
        return int.from_bytes(
            hashlib.blake2b(kata.encode("utf-8"), digest_size=4).digest(),
            "big")

    def encode(self, teks, convert_to_numpy=True, normalize_embeddings=True,
               show_progress_bar=False):
        out = []
        for t in teks:
            v = np.zeros(self.DIM, dtype=np.float32)
            for kata in t.split():
                v[self._slot(kata) % self.DIM] += 1.0
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return np.vstack(out)


def bangun(pasangan):
    """pasangan: [(faq_id, teks)] -> Engine siap pakai."""
    model = ModelTiruan()
    teks = [t for _, t in pasangan]
    vek = model.encode(teks)
    snap = Snapshot(versi=1, vektor=vek.astype(np.float32),
                    pemilik=[i for i, _ in pasangan], dim=ModelTiruan.DIM)
    return Engine(model, snap, tau_high=0.72, tau_low=0.60)


KB = [(1, "apa itu universitas bangka belitung"),
      (2, "berapa uang kuliah tunggal fakultas teknik"),
      (3, "kapan pendaftaran penerimaan mahasiswa baru dibuka")]


def test_engine_siap():
    assert bangun(KB).siap


def test_engine_tanpa_snapshot_tidak_siap():
    assert not Engine(ModelTiruan(), None).siap


def test_cari_mengembalikan_yang_relevan():
    e = bangun(KB)
    hasil = e.cari("apa itu universitas bangka belitung")
    assert hasil[0][0] == 1
    assert hasil[0][1] > 0.9


def test_cari_menghormati_top_k():
    assert len(bangun(KB).cari("universitas", top_k=2)) <= 2


def test_cari_tanpa_snapshot_kosong():
    assert Engine(ModelTiruan(), None).cari("apa pun") == []


def test_snapshot_kosong_aman():
    snap = Snapshot(1, np.zeros((0, 32), dtype=np.float32), [], 32)
    assert Engine(ModelTiruan(), snap).cari("apa pun") == []


def test_satu_faq_tidak_memborong_top_k():
    """Banyak variasi milik FAQ yang sama harus dilipat jadi satu entri."""
    pasangan = [(1, "apa itu ubb"), (1, "ubb itu apa"), (1, "jelaskan ubb"),
                (2, "berapa uang kuliah tunggal")]
    hasil = bangun(pasangan).cari("apa itu ubb", top_k=3)
    ids = [fid for fid, _ in hasil]
    assert len(ids) == len(set(ids)), "faq_id duplikat di hasil"
    assert ids[0] == 1


def test_skor_terurut_menurun():
    skor = [s for _, s in bangun(KB).cari("universitas kuliah teknik", top_k=3)]
    assert skor == sorted(skor, reverse=True)


def test_pasang_snapshot_menukar_index():
    e = bangun(KB)
    lama = e.snapshot
    baru = Snapshot(2, lama.vektor.copy(), lama.pemilik, lama.dim)
    e.pasang_snapshot(baru)
    assert e.snapshot.versi == 2
    # Snapshot lama tetap utuh — immutability yang dijanjikan Bagian 9.3
    assert lama.versi == 1


def test_jawab_lengkap():
    e = bangun(KB)

    def metadata(ids):
        return {1: dict(pertanyaan="Apa itu UBB?", jawaban="PTN di Babel.",
                        kategori="Umum", butuh_verifikasi=False)}

    hasil = e.jawab("apa itu universitas bangka belitung", metadata)
    assert hasil.tipe is Tipe.JAWABAN
    assert hasil.jawaban.startswith("PTN di Babel.")


def test_jawab_saat_engine_belum_siap_tidak_error():
    """Prinsip #6 — model mati, layanan tetap menjawab sopan."""
    hasil = Engine(None, None).jawab("apa itu ubb", lambda ids: {})
    assert hasil.tipe is Tipe.FALLBACK
    assert "Maaf" in hasil.jawaban


def test_jawab_saat_faq_dihapus_setelah_index():
    """metadata kosong = FAQ hilang; harus fallback, bukan KeyError."""
    hasil = bangun(KB).jawab("apa itu universitas bangka belitung", lambda ids: {})
    assert hasil.tipe is Tipe.FALLBACK


def test_pencarian_gagal_tidak_melempar():
    class ModelRusak:
        def encode(self, *a, **kw):
            raise RuntimeError("model rusak")

    snap = Snapshot(1, np.zeros((1, 32), dtype=np.float32), [1], 32)
    hasil = Engine(ModelRusak(), snap).jawab("apa itu ubb", lambda ids: {})
    assert hasil.tipe is Tipe.FALLBACK


def test_cari_mirip_untuk_cek_tabrakan():
    """Fitur paling penting di admin (Bagian 7.2)."""
    e = bangun(KB)
    mirip = e.cari_mirip("apa itu universitas bangka belitung", ambang=0.85)
    assert mirip and mirip[0][0] == 1
    # Entri yang sedang disunting harus diabaikan
    assert e.cari_mirip("apa itu universitas bangka belitung",
                        ambang=0.85, abaikan=1) == []


def test_encode_memakai_normalisasi():
    """Query mentah dan query ternormalisasi harus menghasilkan vektor sama."""
    e = bangun(KB)
    a = e.encode("Apa itu UBB?")
    b = e.encode("apa itu universitas bangka belitung?")
    assert np.allclose(a, b)


def test_encode_batch_dan_tunggal_konsisten():
    e = bangun(KB)
    tunggal = e.encode("apa itu ubb")
    batch = e.encode(["apa itu ubb", "berapa ukt"])
    assert tunggal.shape == (ModelTiruan.DIM,)
    assert batch.shape == (2, ModelTiruan.DIM)
    assert np.allclose(tunggal, batch[0])


# --- Regresi: 502 produksi 2026-08-31 -------------------------------------

def test_muat_engine_global_tahan_permission_error(tmp_path):
    """Direktori artefak yang tidak bisa ditelusuri -> None, BUKAN exception.

    Di produksi `artifacts/model` sempat tidak terbaca user `deploy`.
    `Path.exists()` MELEMPAR PermissionError (tidak mengembalikan False), dan
    saat itu panggilannya ada di luar blok try. Exception naik lewat
    RetrievalConfig.ready(), menjatuhkan seluruh proses gunicorn saat start,
    dan Nginx membalas 502 — padahal prinsip #6 menghendaki layanan tetap
    hidup dengan pesan fallback.
    """
    from retrieval.engine import muat_engine_global

    artefak = tmp_path / "artifacts"
    (artefak / "model").mkdir(parents=True)
    artefak.chmod(0o000)
    try:
        assert muat_engine_global(artefak) is None
    finally:
        artefak.chmod(0o755)      # supaya tmp_path bisa dibersihkan


def test_muat_engine_global_tanpa_model_mengembalikan_none(tmp_path):
    """Artefak ada tapi tanpa model/ — jalur fallback normal."""
    from retrieval.engine import muat_engine_global

    artefak = tmp_path / "artifacts"
    artefak.mkdir()
    assert muat_engine_global(artefak) is None
