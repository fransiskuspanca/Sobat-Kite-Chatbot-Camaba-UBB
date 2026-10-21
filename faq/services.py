"""Jembatan antara admin/faq dan retrieval/.

retrieval/ tidak boleh mengenal Django (Bagian 5), jadi seluruh penerjemahan
model Django <-> tipe primitif terjadi di sini — bukan di dalam retrieval/.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings

from faq.models import Faq, IndexVersion

log = logging.getLogger(__name__)


def muat_engine():
    """Ambil engine global, muat bila belum ada. None bila model tidak tersedia."""
    from retrieval.engine import get_engine, muat_engine_global

    return get_engine() or muat_engine_global(settings.ARTIFACTS_DIR)


def pasang_index_aktif(engine) -> int | None:
    """Muat IndexVersion aktif dari basis data ke engine. Kembalikan versinya."""
    from retrieval.engine import Snapshot
    from retrieval.indexer import dari_bytes

    iv = IndexVersion.objects.filter(aktif=True).first()
    if iv is None:
        return None
    if engine.snapshot is not None and engine.snapshot.versi == iv.versi:
        return iv.versi     # sudah terpasang, jangan buang CPU

    engine.pasang_snapshot(Snapshot(
        iv.versi, dari_bytes(bytes(iv.vektor), iv.dim), iv.pemilik, iv.dim))
    pasang_penjaga(engine)
    return iv.versi


def buat_penjaga(entri: list[dict]):
    """Penjaga domain dari entri index, atau None bila dimatikan/gagal.

    Gagal membangun penjaga tidak boleh menghentikan layanan (prinsip #6):
    chatbot tetap menjawab, hanya tanpa penjagaan kata.
    """
    if not getattr(settings, "PENJAGA_DOMAIN", True):
        return None
    try:
        from retrieval.domain import PenjagaDomain
        return PenjagaDomain(entri)
    except Exception:
        log.exception("Penjaga domain gagal dibangun — dilewati")
        return None


def pasang_penjaga(engine) -> None:
    """Bangun penjaga dari FAQ + variasi di basis data dan pasang ke engine."""
    from faq.actions import kumpulkan_entri

    try:
        entri, _ = kumpulkan_entri()
    except Exception:
        log.exception("Gagal mengumpulkan entri untuk penjaga domain")
        entri = []
    engine.penjaga = buat_penjaga(entri) if entri else None


# Deteksi versi antar-proses (Bagian 9.3).
#
# Dengan 3 worker, reindex dari proses admin TIDAK otomatis terlihat oleh
# worker API. Solusi paling sederhana dan cukup andal: setiap worker
# memeriksa versi aktif setiap N detik (query sangat murah — satu kolom,
# satu baris), lalu memuat ulang bila berbeda.
#
# Redis pub/sub lebih rapi, tapi sengaja tidak dibangun di awal.
INTERVAL_CEK_VERSI = 10        # detik

_terakhir_dicek = 0.0


def _perlu_cek_versi() -> bool:
    global _terakhir_dicek
    sekarang = time.monotonic()
    if sekarang - _terakhir_dicek < INTERVAL_CEK_VERSI:
        return False
    _terakhir_dicek = sekarang
    return True


def sinkronkan_versi(engine) -> int | None:
    """Muat ulang index bila proses lain sudah menggantinya.

    Dipanggil di jalur request; sengaja dibuat murah dan gagal-diam.
    """
    if engine is None:
        return None
    try:
        versi_db = (IndexVersion.objects.filter(aktif=True)
                    .values_list("versi", flat=True).first())
    except Exception:
        log.exception("Gagal memeriksa versi index aktif")
        return engine.snapshot.versi if engine.snapshot else None

    if versi_db is None:
        return None

    sekarang = engine.snapshot.versi if engine.snapshot else None
    if sekarang != versi_db:
        log.info("Index berubah di proses lain: v%s -> v%s. Memuat ulang.",
                 sekarang, versi_db)
        engine._snapshot = None
        return pasang_index_aktif(engine)
    return sekarang


def engine_siap():
    """Engine dengan index aktif terpasang, atau None."""
    engine = muat_engine()
    if engine is None:
        return None

    if engine.snapshot is None:
        if pasang_index_aktif(engine) is None:
            return None
    elif _perlu_cek_versi():
        # Reindex/rollback dari proses admin menyusul ke sini.
        if sinkronkan_versi(engine) is None:
            return None

    return engine


def cari_tabrakan(pertanyaan: str, abaikan_pk: int | None = None,
                  ambang: float = 0.85) -> list[dict]:
    """Cari FAQ yang sangat mirip dengan `pertanyaan`.

    Dua entri yang praktis sama membuat retrieval ambigu SELAMANYA — tidak ada
    model yang bisa memilih dengan benar di antara keduanya. Mencegahnya di
    titik input jauh lebih murah daripada mendeteksinya tiga bulan kemudian.

    Kegagalan di sini tidak boleh menghalangi admin menyimpan (prinsip #6):
    kalau engine mati, kembalikan daftar kosong.
    """
    try:
        engine = engine_siap()
        if engine is None:
            return []
        mirip = engine.cari_mirip(pertanyaan, ambang=ambang, abaikan=abaikan_pk)
    except Exception:
        log.exception("Cek tabrakan gagal untuk %r", pertanyaan[:80])
        return []

    if not mirip:
        return []

    peta = {f.id: f for f in Faq.objects.filter(id__in=[i for i, _ in mirip])}
    keluar = []
    for faq_id, skor in mirip:
        f = peta.get(faq_id)
        if f is not None:
            keluar.append({"faq": f, "skor": skor})
    return keluar
