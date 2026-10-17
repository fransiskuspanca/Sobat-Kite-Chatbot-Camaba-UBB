"""Bangun ulang index + regression gate.

Modul ini bekerja dengan tipe primitif saja — pemanggil (faq/actions.py di
Fase 3) yang mengambil baris dari basis data dan menyerahkannya ke sini.
Dengan begitu retrieval/ tetap tidak mengenal Django.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .engine import Engine, Snapshot

log = logging.getLogger(__name__)

AMBANG_ACC_DEFAULT = 0.85     # Bagian 9.4


@dataclass
class HasilIndex:
    snapshot: Snapshot
    jumlah_answer: int
    acc_at_1: float | None = None
    lolos: bool = True
    gagal: list[dict] = None
    catatan: str = ""


def bangun_snapshot(engine: Engine, entri: list[dict], versi: int) -> Snapshot:
    """entri: [{"faq_id": int, "teks": str}] — pertanyaan kanonik + variasi.

    Satu baris = satu vektor. Beberapa vektor boleh menunjuk faq_id yang sama;
    itulah cara variasi menaikkan akurasi tanpa melatih ulang model.
    """
    if not entri:
        raise ValueError("Tidak ada entri untuk di-index.")

    teks = [e["teks"] for e in entri]
    pemilik = [int(e["faq_id"]) for e in entri]

    # doc-side: prefix dokumen, bukan prefix query (penting untuk keluarga E5)
    vektor = engine.encode(teks, is_query=False)
    vektor = np.ascontiguousarray(vektor, dtype=np.float32)

    return Snapshot(versi=versi, vektor=vektor, pemilik=pemilik,
                    dim=int(vektor.shape[1]))


def evaluasi(engine: Engine, snapshot: Snapshot,
             hard_eval: dict[str, list[str]],
             peta_pertanyaan: dict[str, int]) -> tuple[float, list[dict]]:
    """Acc@1 terhadap hard eval set.

    hard_eval      : {pertanyaan_kanonik: [parafrase, ...]}
    peta_pertanyaan: {pertanyaan_kanonik: faq_id}

    Dipetakan lewat TEKS kanonik (bukan ID) supaya tetap valid meski urutan
    baris di Excel berubah — mengikuti catatan notebook sel 5.
    """
    # Pakai snapshot kandidat, bukan yang sedang aktif.
    penguji = Engine(engine.model, snapshot,
                     tau_high=engine.tau_high, tau_low=engine.tau_low,
                     top_k=1, query_prefix=engine.query_prefix,
                     doc_prefix=engine.doc_prefix)

    benar = 0
    total = 0
    gagal: list[dict] = []

    for kanonik, parafrase in hard_eval.items():
        emas = peta_pertanyaan.get(" ".join(kanonik.lower().split()))
        if emas is None:
            log.warning("Hard eval menyebut pertanyaan yang tidak ada di KB: %r",
                        kanonik[:70])
            continue
        for q in parafrase:
            total += 1
            hits = penguji.cari(q, top_k=1)
            if hits and hits[0][0] == emas:
                benar += 1
            else:
                gagal.append({
                    "query": q,
                    "harapan": kanonik,
                    "dapat_faq_id": hits[0][0] if hits else None,
                    "skor": round(hits[0][1], 4) if hits else 0.0,
                })

    return (benar / total if total else 0.0), gagal


def bangun_dan_uji(engine: Engine, entri: list[dict], versi: int,
                   hard_eval: dict | None = None,
                   peta_pertanyaan: dict | None = None,
                   ambang: float = AMBANG_ACC_DEFAULT) -> HasilIndex:
    """Bangun index kandidat, uji, putuskan boleh dipasang atau tidak.

    Reindex TIDAK PERNAH mengubah index yang sedang dipakai — snapshot baru
    hanya dipasang oleh pemanggil bila `lolos` True.
    """
    snapshot = bangun_snapshot(engine, entri, versi)
    jumlah_answer = len(set(snapshot.pemilik))

    if not hard_eval:
        # Bagian 9.4: tampilkan status ini dengan jelas, jangan sampai admin
        # mengira terlindungi padahal belum.
        return HasilIndex(snapshot, jumlah_answer, None, True, [],
                          "hard_eval.json tidak tersedia — regression gate DILEWATI.")

    acc, gagal = evaluasi(engine, snapshot, hard_eval, peta_pertanyaan or {})
    lolos = acc >= ambang
    catatan = (f"Acc@1 {acc:.3f} {'≥' if lolos else '<'} ambang {ambang:.2f} — "
               f"{'index dipasang' if lolos else 'DITOLAK, versi lama tetap melayani'}")
    return HasilIndex(snapshot, jumlah_answer, acc, lolos, gagal, catatan)


# --- serialisasi untuk IndexVersion.vektor (BinaryField) -----------------

def ke_bytes(vektor: np.ndarray) -> bytes:
    return np.ascontiguousarray(vektor, dtype=np.float32).tobytes()


def dari_bytes(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).reshape(-1, dim)


def muat_hard_eval(path: str | Path) -> dict | None:
    """Baca hard_eval.json dan kembalikan {kanonik: [parafrase, ...]}.

    Notebook mengeluarkan dua bentuk, tergantung versinya:
      1. dict  {pertanyaan_kanonik: [parafrase, ...]}      — dipakai apa adanya
      2. list  [{"query": ..., "answer_id": n}, ...]       — n adalah INDEKS
         baris knowledge_base.json, bukan Faq.id di basis data.

    Bentuk 2 dinormalisasi ke bentuk 1 lewat teks kanonik, karena `evaluasi()`
    memetakan ke faq_id lewat TEKS (lihat catatan notebook sel 5): indeks baris
    artefak tidak sama dengan id auto-increment Django.
    """
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        return data
    if not isinstance(data, list):
        log.warning("%s berisi %s — hard eval diabaikan, regression gate lewat.",
                    p, type(data).__name__)
        return None

    kb_path = p.parent / "knowledge_base.json"
    if not kb_path.exists():
        log.warning("%s memakai answer_id numerik tetapi %s tidak ada — "
                    "hard eval diabaikan, regression gate DILEWATI.", p, kb_path)
        return None
    with open(kb_path, encoding="utf-8") as f:
        kb = json.load(f)

    hasil: dict[str, list[str]] = {}
    for baris in data:
        try:
            idx = int(baris["answer_id"])
            query = baris["query"]
        except (KeyError, TypeError, ValueError):
            log.warning("Entri hard eval tidak dikenali, dilewati: %r", baris)
            continue
        if not 0 <= idx < len(kb):
            log.warning("answer_id %s di luar jangkauan knowledge_base (%d baris) "
                        "— query %r dilewati", idx, len(kb), query[:50])
            continue
        kanonik = kb[idx].get("pertanyaan", "")
        if not kanonik:
            log.warning("Baris knowledge_base %s tanpa pertanyaan — query %r dilewati",
                        idx, query[:50])
            continue
        hasil.setdefault(kanonik, []).append(query)

    return hasil or None
