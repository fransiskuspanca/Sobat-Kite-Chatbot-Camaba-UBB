"""Mesin retrieval — bi-encoder + pencarian kosinus.

Port sinkron dari engine FastAPI. Gunicorn sync worker berarti encode() yang
memblokir hanya menahan satu worker, bukan membekukan event loop — seluruh
kerumitan anyio.to_thread lenyap.

⚠️  Modul ini TIDAK BOLEH mengimpor faq/ atau api/ (Bagian 5 dokumen rencana).
Ia menerima teks + vektor, mengembalikan skor. Dengan begitu ia bisa diuji
tanpa Django dan tanpa basis data.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .text import normalize
from .tiers import (Kandidat, Keputusan, Tipe, keputusan_darurat, putuskan,
                    tampak_lanjutan)

log = logging.getLogger(__name__)

# Prinsip #3: ambang default condong ke precision. Ditimpa config.json artefak
# Colab, lalu boleh ditimpa environment.
TAU_HIGH_DEFAULT = 0.72
TAU_LOW_DEFAULT = 0.60
TOP_K_DEFAULT = 3


@dataclass(frozen=True)
class Snapshot:
    """Index immutable. Reindex membuat objek BARU, tidak pernah mengubah ini.

    Request yang sedang berjalan tetap memakai snapshot lamanya sampai selesai —
    tanpa penguncian, tanpa kemungkinan membaca index setengah jadi.
    """
    versi: int
    vektor: np.ndarray            # (n, dim) float32, sudah L2-normalized
    pemilik: list[int]            # faq_id sepanjang n
    dim: int

    @property
    def jumlah_vektor(self) -> int:
        return int(self.vektor.shape[0])


class Engine:
    """Memegang model + snapshot index. Aman dipakai lintas thread untuk baca."""

    def __init__(self, model, snapshot: Snapshot | None = None, *,
                 tau_high: float = TAU_HIGH_DEFAULT,
                 tau_low: float = TAU_LOW_DEFAULT,
                 top_k: int = TOP_K_DEFAULT,
                 query_prefix: str = "", doc_prefix: str = ""):
        self.model = model
        self._snapshot = snapshot
        self.tau_high = tau_high
        self.tau_low = tau_low
        self.top_k = top_k
        self.query_prefix = query_prefix
        self.doc_prefix = doc_prefix
        self.penjaga = None       # PenjagaDomain; None = penjaga mati
        self._lock = threading.Lock()

    # --- snapshot -------------------------------------------------------

    @property
    def snapshot(self) -> Snapshot | None:
        return self._snapshot

    def pasang_snapshot(self, snapshot: Snapshot) -> None:
        """Tukar satu referensi. Atomik dari sudut pandang pembaca."""
        with self._lock:
            self._snapshot = snapshot
        log.info("Index v%s dipasang (%s vektor, dim %s)",
                 snapshot.versi, snapshot.jumlah_vektor, snapshot.dim)

    @property
    def siap(self) -> bool:
        return self.model is not None and self._snapshot is not None

    # --- encoding -------------------------------------------------------

    def encode(self, teks: str | list[str], *, is_query: bool = True) -> np.ndarray:
        """Normalisasi + encode. Prefix mengikuti keluarga model (E5 dsb)."""
        prefix = self.query_prefix if is_query else self.doc_prefix
        satuan = isinstance(teks, str)
        daftar = [teks] if satuan else list(teks)
        siap = [prefix + normalize(t) for t in daftar]
        vek = self.model.encode(siap, convert_to_numpy=True,
                                normalize_embeddings=True,
                                show_progress_bar=False)
        vek = np.asarray(vek, dtype=np.float32)
        return vek[0] if satuan else vek

    # --- pencarian ------------------------------------------------------

    def cari(self, query: str, top_k: int | None = None) -> list[tuple[int, float]]:
        """Kembalikan [(faq_id, skor)] terurut menurun, satu entri per faq_id.

        1.300 vektor = satu perkalian matriks NumPy, < 1 ms. Itu sebabnya
        tidak ada vector database di sini.
        """
        snap = self._snapshot
        if snap is None or snap.jumlah_vektor == 0:
            return []

        k = top_k or self.top_k
        q = self.encode(query, is_query=True)
        skor = snap.vektor @ q          # kosinus: keduanya sudah dinormalisasi

        # Satu faq bisa punya banyak vektor (variasi). Ambil skor TERTINGGI
        # per faq, kalau tidak satu FAQ akan memborong seluruh top-k.
        terbaik: dict[int, float] = {}
        for idx in np.argsort(-skor):
            fid = snap.pemilik[int(idx)]
            s = float(skor[int(idx)])
            if fid not in terbaik or s > terbaik[fid]:
                terbaik[fid] = s
            if len(terbaik) >= k and s < min(terbaik.values()):
                break

        return sorted(terbaik.items(), key=lambda x: -x[1])[:k]

    def cari_mirip(self, teks: str, ambang: float = 0.85,
                   abaikan: int | None = None) -> list[tuple[int, float]]:
        """Untuk cek tabrakan di admin (Bagian 7.2). Dipakai Fase 1."""
        hasil = self.cari(teks, top_k=5)
        return [(fid, s) for fid, s in hasil
                if s >= ambang and (abaikan is None or fid != abaikan)]

    # --- keputusan lengkap ----------------------------------------------

    def _kandidat(self, teks: str, pengambil_metadata,
                  abaikan: int | None = None) -> list[Kandidat]:
        """Cari `teks` lalu lengkapi dengan metadata. `abaikan` dibuang dari hasil."""
        hits = self.cari(teks, top_k=self.top_k + (1 if abaikan else 0))
        hits = [(fid, s) for fid, s in hits if fid != abaikan][:self.top_k]
        if not hits:
            return []
        meta = pengambil_metadata([fid for fid, _ in hits])
        # FAQ yang dihapus setelah index dibangun tidak punya metadata.
        return [Kandidat(faq_id=fid, skor=skor, **meta[fid])
                for fid, skor in hits if fid in meta]

    def jawab(self, query: str, pengambil_metadata,
              pesan_identitas: str = "", template_fallback: str = "",
              fallback_tanpa_kunci: str = "", konteks: str = "",
              faq_sebelumnya: int | None = None) -> Keputusan:
        """Pencarian + empat tier.

        `pengambil_metadata` adalah callable(list[faq_id]) -> dict[faq_id, dict].
        `pesan_identitas` dan `template_fallback` berasal dari pengaturan
        admin. Semuanya disuntikkan dari luar supaya modul ini tetap tidak
        mengenal Django.

        `konteks` adalah pertanyaan FAQ yang terakhir dijawab dalam sesi yang
        sama (`faq_sebelumnya` id-nya). Pertanyaan lanjutan yang tidak utuh
        ("apa saja?", "kalau biayanya?") tidak bisa dijawab sendirian; bila
        pencarian biasa gagal, ia dicari ulang bersama konteks itu. FAQ yang
        sudah dijawab dilewati, karena pertanyaan lanjutan menanyakan hal baru.
        """
        if not self.siap:
            return keputusan_darurat()

        def _putuskan(kandidat, teks):
            p = self.penjaga
            luar = bool(p) and p.di_luar_domain(teks)
            lepas = (bool(p) and not luar and bool(kandidat)
                     and not p.nyambung(teks, kandidat[0].faq_id))
            return putuskan(query, kandidat, self.tau_high, self.tau_low,
                            pesan_identitas, template_fallback,
                            fallback_tanpa_kunci, luar_domain=luar,
                            tidak_nyambung=lepas)

        try:
            keputusan = _putuskan(self._kandidat(query, pengambil_metadata), query)
        except Exception:                      # prinsip #6: jangan HTTP 500
            log.exception("Pencarian gagal untuk query %r", query[:80])
            return keputusan_darurat()

        # Pertanyaan di luar domain tidak boleh "diselamatkan" konteks:
        # "resep nasi goreng" setelah bertanya UKT tetap di luar domain.
        luar_domain = bool(self.penjaga) and self.penjaga.di_luar_domain(query)
        if not (konteks and keputusan.tipe in (Tipe.FALLBACK, Tipe.KLARIFIKASI)
                and tampak_lanjutan(query) and not luar_domain):
            return keputusan

        try:
            gabungan = f"{konteks} {query}"
            lanjutan = _putuskan(self._kandidat(gabungan, pengambil_metadata,
                                                abaikan=faq_sebelumnya), gabungan)
        except Exception:
            log.exception("Pencarian lanjutan gagal untuk query %r", query[:80])
            return keputusan

        # Konteks hanya dipakai bila hasilnya lebih pasti dari pencarian biasa.
        lebih_pasti = (lanjutan.tipe in (Tipe.JAWABAN, Tipe.ESKALASI)
                       or (lanjutan.tipe == Tipe.KLARIFIKASI
                           and keputusan.tipe == Tipe.FALLBACK))
        return lanjutan if lebih_pasti else keputusan


# --- engine global (satu per proses) -------------------------------------

_ENGINE: Engine | None = None


def get_engine() -> Engine | None:
    return _ENGINE


def set_engine(engine: Engine | None) -> None:
    global _ENGINE
    _ENGINE = engine


def baca_config(path: str | Path) -> dict:
    """Baca config.json artefak Colab (tau_high, tau_low, prefix)."""
    p = Path(path)
    if not p.exists():
        log.warning("config.json tidak ada di %s — memakai ambang default", p)
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def muat_engine_global(artifacts_dir: str | Path = "artifacts") -> Engine | None:
    """Muat model dari disk. Dipanggil RetrievalConfig.ready() di proses server.

    Kegagalan di sini TIDAK boleh menjatuhkan proses — layanan tetap hidup dan
    menjawab dengan pesan sopan (prinsip #6).
    """
    global _ENGINE
    d = Path(artifacts_dir)
    model_dir = d / "model"

    try:
        # exists() HARUS di dalam try: ia melempar PermissionError (bukan
        # mengembalikan False) bila salah satu direktori induk tidak bisa
        # ditelusuri. Di produksi itu pernah menjatuhkan seluruh proses
        # gunicorn lewat AppConfig.ready() -> Nginx 502, padahal seharusnya
        # cukup jadi fallback sopan (prinsip #6).
        if not model_dir.exists():
            log.warning("Model belum ada di %s. Engine tidak dimuat; "
                        "API akan menjawab dengan pesan fallback.", model_dir)
            return None

        from sentence_transformers import SentenceTransformer
        import torch

        # Dua core, tiga proses. Membiarkan torch memakai kedua core justru
        # memperlambat karena antar-proses rebutan CPU.
        torch.set_num_threads(1)

        cfg = baca_config(d / "config.json")
        model = SentenceTransformer(str(model_dir), device="cpu")
        _ENGINE = Engine(
            model,
            tau_high=float(cfg.get("tau_high", TAU_HIGH_DEFAULT)),
            tau_low=float(cfg.get("tau_low", TAU_LOW_DEFAULT)),
            top_k=int(cfg.get("top_k", TOP_K_DEFAULT)),
            query_prefix=cfg.get("query_prefix", ""),
            doc_prefix=cfg.get("doc_prefix", ""),
        )
        log.info("Engine dimuat: tau_high=%s tau_low=%s",
                 _ENGINE.tau_high, _ENGINE.tau_low)
        return _ENGINE
    except Exception:
        log.exception("Gagal memuat model — layanan tetap jalan tanpa engine")
        return None
