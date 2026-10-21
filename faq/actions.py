"""Aksi yang mengubah keadaan sistem: reindex, rollback, ekspor.

Dipakai bersama oleh perintah manage.py DAN tombol di admin, supaya keduanya
tidak pernah menyimpang perilakunya.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from faq.models import Faq, IndexVersion

log = logging.getLogger(__name__)


# --- status proses latar ---------------------------------------------------

@dataclass
class StatusReindex:
    """Keadaan reindex yang sedang berjalan.

    Reindex memakan 20-40 detik untuk 1.300 vektor. Menjalankannya di dalam
    request HTTP berarti browser admin menggantung selama itu — karena itu
    prosesnya dipindah ke thread dan halaman menanyakan statusnya.
    """
    berjalan: bool = False
    mulai: object = None
    selesai: object = None
    tahap: str = ""
    berhasil: bool | None = None
    pesan: str = ""
    versi_baru: int | None = None
    acc_at_1: float | None = None
    gagal: list = field(default_factory=list)

    def sebagai_dict(self):
        return {
            "berjalan": self.berjalan,
            "tahap": self.tahap,
            "berhasil": self.berhasil,
            "pesan": self.pesan,
            "versi_baru": self.versi_baru,
            "acc_at_1": self.acc_at_1,
            "gagal": self.gagal[:10],
            "mulai": self.mulai.isoformat() if self.mulai else None,
            "selesai": self.selesai.isoformat() if self.selesai else None,
        }


_status = StatusReindex()
_kunci = threading.Lock()


def status_reindex() -> StatusReindex:
    return _status


def ambang_default() -> float:
    """Dibungkus fungsi agar admin tidak mengimpor numpy saat startup."""
    from retrieval.indexer import AMBANG_ACC_DEFAULT
    return AMBANG_ACC_DEFAULT


# --- pengumpulan entri -----------------------------------------------------

def kumpulkan_entri() -> tuple[list[dict], dict[str, int]]:
    """Pertanyaan kanonik + seluruh variasi = satu vektor per baris.

    Entri butuh_verifikasi TETAP disertakan supaya niat camaba tetap dikenali;
    penggantian jawabannya terjadi saat runtime (prinsip #4).
    """
    entri, peta = [], {}
    for f in (Faq.objects.filter(aktif=True)
              .prefetch_related("variasi").order_by("id")):
        entri.append({"faq_id": f.id, "teks": f.pertanyaan})
        peta[" ".join(f.pertanyaan.lower().split())] = f.id
        for v in f.variasi.all():
            entri.append({"faq_id": f.id, "teks": v.teks})
    return entri, peta


# --- reindex ---------------------------------------------------------------

def jalankan_reindex(*, ambang: float | None = None, paksa: bool = False,
                     pengguna: str = "") -> StatusReindex:
    """Bangun index kandidat, uji, pasang bila lolos.

    Sinkron — pemanggil yang memutuskan mau di thread atau tidak.
    """
    from retrieval.indexer import (AMBANG_ACC_DEFAULT, bangun_dan_uji,
                                   ke_bytes, muat_hard_eval)

    from faq.services import muat_engine

    _status.tahap = "memuat model"
    engine = muat_engine()
    if engine is None:
        raise RuntimeError(
            f"Model tidak tersedia di {settings.ARTIFACTS_DIR}/model/. "
            "Jalankan: python manage.py siapkan_model")

    _status.tahap = "mengumpulkan FAQ"
    entri, peta = kumpulkan_entri()
    if not entri:
        raise RuntimeError("Tidak ada FAQ aktif — jalankan import_colab dulu.")

    versi = (IndexVersion.objects.order_by("-versi")
             .values_list("versi", flat=True).first() or 0) + 1

    _status.tahap = f"meng-encode {len(entri)} vektor"
    hard_eval = muat_hard_eval(settings.ARTIFACTS_DIR / "hard_eval.json")
    hasil = bangun_dan_uji(engine, entri, versi, hard_eval, peta,
                           ambang if ambang is not None else AMBANG_ACC_DEFAULT)

    _status.acc_at_1 = hasil.acc_at_1
    _status.gagal = hasil.gagal or []

    if not hasil.lolos and not paksa:
        # Regression gate menolak: versi lama TETAP melayani.
        _status.berhasil = False
        _status.pesan = hasil.catatan
        return _status

    _status.tahap = "menyimpan index"
    snap = hasil.snapshot
    catatan = hasil.catatan + (" [DIPAKSA]" if paksa and not hasil.lolos else "")
    if pengguna:
        catatan += f" · oleh {pengguna}"

    with transaction.atomic():
        IndexVersion.objects.filter(aktif=True).update(aktif=False)
        IndexVersion.objects.create(
            versi=versi, vektor=ke_bytes(snap.vektor), pemilik=snap.pemilik,
            dim=snap.dim, jumlah_vektor=snap.jumlah_vektor,
            jumlah_answer=hasil.jumlah_answer, acc_at_1=hasil.acc_at_1,
            catatan=catatan, aktif=True)

    engine.pasang_snapshot(snap)
    from faq.services import buat_penjaga
    engine.penjaga = buat_penjaga(entri)

    _status.berhasil = True
    _status.versi_baru = versi
    _status.pesan = (f"Index v{versi} aktif — {snap.jumlah_vektor} vektor, "
                     f"{hasil.jumlah_answer} jawaban.")
    return _status


def mulai_reindex_latar(*, ambang: float | None = None, paksa: bool = False,
                        pengguna: str = "") -> bool:
    """Jalankan reindex di thread terpisah. False bila sudah ada yang jalan."""
    global _status

    with _kunci:
        if _status.berjalan:
            return False
        _status = StatusReindex(berjalan=True, mulai=timezone.now(),
                                tahap="menyiapkan")

    def kerja():
        try:
            jalankan_reindex(ambang=ambang, paksa=paksa, pengguna=pengguna)
        except Exception as e:
            log.exception("Reindex gagal")
            _status.berhasil = False
            _status.pesan = str(e)
        finally:
            _status.berjalan = False
            _status.tahap = ""
            _status.selesai = timezone.now()

    threading.Thread(target=kerja, daemon=True,
                     name="reindex").start()
    return True


# --- rollback --------------------------------------------------------------

def rollback(versi: int, pengguna: str = "") -> IndexVersion:
    """Aktifkan kembali versi index lama.

    Langkah pertama di runbook saat chatbot menjawab ngawur setelah update.
    Tidak ada encode ulang — vektornya sudah tersimpan di basis data.
    """
    target = IndexVersion.objects.get(versi=versi)

    with transaction.atomic():
        IndexVersion.objects.filter(aktif=True).update(aktif=False)
        target.aktif = True
        catatan = f"Rollback pada {timezone.now():%d %b %Y %H:%M}"
        if pengguna:
            catatan += f" oleh {pengguna}"
        target.catatan = (target.catatan + " · " if target.catatan else "") + catatan
        target.save(update_fields=["aktif", "catatan"])

    # Terapkan langsung ke proses ini; worker lain menyusul lewat polling.
    try:
        from faq.services import muat_engine, pasang_index_aktif
        engine = muat_engine()
        if engine is not None:
            engine._snapshot = None      # paksa muat ulang dari basis data
            pasang_index_aktif(engine)
    except Exception:
        log.exception("Gagal menerapkan rollback ke engine proses ini")

    return target
