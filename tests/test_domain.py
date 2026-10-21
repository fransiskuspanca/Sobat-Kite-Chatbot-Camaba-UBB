"""Penjaga domain: pertanyaan di luar topik tidak dijawab dengan yakin."""

import json
from pathlib import Path

import numpy as np

from retrieval.domain import PenjagaDomain, kata_isi
from retrieval.engine import Engine, Snapshot
from retrieval.tiers import Kandidat, Tipe, putuskan

ENTRI = [
    {"faq_id": 1, "teks": "Berapa biaya UKT di UBB?"},
    {"faq_id": 1, "teks": "uang kuliah tunggal per semester berapa"},
    {"faq_id": 1, "teks": "biaya kuliah tiap semester"},
    {"faq_id": 2, "teks": "Bagaimana UBB menentukan kelompok UKT?"},
    {"faq_id": 2, "teks": "penentuan kelompok ukt berdasarkan apa"},
    {"faq_id": 3, "teks": "Kapan pendaftaran jalur mandiri dibuka?"},
    {"faq_id": 3, "teks": "jadwal pendaftaran mandiri"},
    {"faq_id": 4, "teks": "Apakah tersedia asrama mahasiswa?"},
    {"faq_id": 4, "teks": "asrama buat anak rantau ada"},
]


def test_kata_umum_dan_angka_dibuang():
    assert kata_isi("apa resep nasi goreng 2026?") == ["resep", "nasi", "goreng"]


def test_luar_domain_dikenali():
    p = PenjagaDomain(ENTRI)
    assert p.di_luar_domain("apa resep nasi goreng?")
    assert p.di_luar_domain("siapa prabowo subianto")


def test_dalam_domain_tidak_ditolak():
    p = PenjagaDomain(ENTRI)
    assert not p.di_luar_domain("ukt per semester brp")
    assert not p.di_luar_domain("kapan daftar mandiri")       # imbuhan
    assert not p.di_luar_domain("pendaftaarn mandiri kapan")  # salah ketik


def test_query_tanpa_kata_isi_tidak_dinilai():
    assert not PenjagaDomain(ENTRI).di_luar_domain("apa ya?")


def test_tidak_nyambung_dengan_faq_lain():
    p = PenjagaDomain(ENTRI)
    assert p.nyambung("pendaftaran mandiri kapan", 3)
    assert not p.nyambung("asrama ada?", 3)


def test_penjaga_kosong_tidak_menolak():
    p = PenjagaDomain([])
    assert not p.di_luar_domain("resep nasi goreng")
    assert p.nyambung("resep nasi goreng", 1)


def _kandidat(skor=0.9):
    return [Kandidat(1, "Berapa biaya UKT?", skor, jawaban="UKT ..."),
            Kandidat(2, "Bagaimana menentukan kelompok UKT?", skor - 0.01)]


def test_tier_luar_domain_fallback_walau_skor_tinggi():
    k = putuskan("apa resep nasi goreng", _kandidat(), 0.72, 0.60, luar_domain=True)
    assert k.tipe == Tipe.FALLBACK
    assert k.kandidat                       # tetap tercatat untuk log


def test_tier_tidak_nyambung_jadi_klarifikasi():
    k = putuskan("berapa jumlah lulusan", _kandidat(), 0.72, 0.60, tidak_nyambung=True)
    assert k.tipe == Tipe.KLARIFIKASI


class ModelSemuaSama:
    """Setiap teks mendapat vektor yang sama: skor selalu 1.0.

    Meniru kasus nyata model kecil yang memberi skor tinggi pada pertanyaan
    yang tidak berhubungan.
    """

    def encode(self, teks, **_):
        return np.ones((len(teks), 4), dtype=np.float32) / 2


def _engine(penjaga=True):
    snap = Snapshot(versi=1, vektor=np.ones((len(ENTRI), 4), dtype=np.float32) / 2,
                    pemilik=[e["faq_id"] for e in ENTRI], dim=4)
    e = Engine(ModelSemuaSama(), snap, tau_high=0.72, tau_low=0.60)
    if penjaga:
        e.penjaga = PenjagaDomain(ENTRI)
    return e


def _meta(ids):
    teks = {e["faq_id"]: e["teks"] for e in reversed(ENTRI)}
    return {i: {"pertanyaan": teks[i], "jawaban": f"jawaban {i}"} for i in ids}


def test_engine_tanpa_penjaga_menjawab_resep():
    """Kondisi sebelum perbaikan: skor tinggi = dijawab."""
    assert _engine(penjaga=False).jawab("apa resep nasi goreng?", _meta).tipe == Tipe.JAWABAN


def test_engine_dengan_penjaga_fallback():
    assert _engine().jawab("apa resep nasi goreng?", _meta).tipe == Tipe.FALLBACK


def test_engine_luar_domain_tidak_diselamatkan_konteks():
    k = _engine().jawab("resep nasi goreng", _meta,
                        konteks="Berapa biaya UKT di UBB?", faq_sebelumnya=1)
    assert k.tipe == Tipe.FALLBACK


def test_engine_tidak_nyambung_klarifikasi():
    # Semua skor sama, jadi FAQ teratas belum tentu FAQ asrama.
    k = _engine().jawab("asrama rantau", _meta)
    assert k.tipe in (Tipe.JAWABAN, Tipe.KLARIFIKASI)
    if k.tipe == Tipe.JAWABAN:
        assert k.faq_id == 4


AKAR = Path(__file__).resolve().parent.parent


def _penjaga_data_nyata():
    """Penjaga dari Excel FAQ terbaru + paket sinkron, seperti di server."""
    from faq.management.commands.import_colab import (parse_faq_excel,
                                                      parse_variasi_excel)

    xlsx = sorted((AKAR / "data").glob("FAQ_Sobat_Kite_Fix_v*.xlsx"),
                  key=lambda p: int(p.stem.rsplit("v", 1)[1]))[-1]
    faq, _ = parse_faq_excel(xlsx)
    ids = {" ".join(f["pertanyaan"].lower().split()): i for i, f in enumerate(faq)}
    entri = [{"faq_id": i, "teks": f["pertanyaan"]} for i, f in enumerate(faq)]

    def tambah(tanya, teks):
        k = " ".join(tanya.lower().split())
        if k not in ids:
            ids[k] = len(ids)
        entri.append({"faq_id": ids[k], "teks": teks})

    for tanya, var in parse_variasi_excel(xlsx)[0]:
        tambah(tanya, var)
    sinkron = AKAR / "data" / "sinkron"
    for nama in json.loads((sinkron / "daftar.json").read_text(encoding="utf-8")):
        paket = json.loads((sinkron / nama).read_text(encoding="utf-8"))
        for tanya, daftar in (paket.get("variasi") or {}).items():
            for t in daftar:
                tambah(tanya, t)
        for f in paket.get("faq_baru") or []:
            tambah(f["pertanyaan"], f["pertanyaan"])
            for t in f.get("variasi") or []:
                tambah(f["pertanyaan"], t)
    return PenjagaDomain(entri), ids


def _baca_uji(nama):
    teks = (AKAR / "data" / "uji" / nama).read_text(encoding="utf-8")
    return [b.strip() for b in teks.splitlines() if b.strip() and not b.startswith("#")]


def test_hard_eval_tidak_ditolak():
    """Pertanyaan camaba di hard eval tidak boleh ditolak penjaga terhadap
    FAQ yang benar."""
    p, ids = _penjaga_data_nyata()
    he = json.loads((AKAR / "artifacts" / "hard_eval.json").read_text(encoding="utf-8"))
    tertolak = [q for k, qs in he.items() for q in qs
                if p.tolak(q, ids.get(" ".join(k.lower().split())))]
    # Satu-satunya pengecualian: kata pembedanya (konstruksi, bangunan) tidak
    # dipakai FAQ mana pun, jadi ditawarkan sebagai klarifikasi, bukan fallback.
    assert tertolak in ([], ["kalau mau belajar konstruksi bangunan masuk prodi apa"]), tertolak
    assert not [q for qs in he.values() for q in qs if p.di_luar_domain(q)]


def test_pertanyaan_camaba_tidak_dianggap_luar_domain():
    p, _ = _penjaga_data_nyata()
    tertolak = [q for q in _baca_uji("dalam_topik.txt") if p.di_luar_domain(q)]
    assert not tertolak, tertolak


def test_pertanyaan_luar_topik_sebagian_besar_dikenali():
    """Sisanya ditangani pemeriksaan nyambung terhadap FAQ teratas."""
    p, _ = _penjaga_data_nyata()
    daftar = _baca_uji("luar_topik.txt")
    dikenali = [q for q in daftar if p.di_luar_domain(q)]
    assert "apa resep nasi goreng?" in dikenali
    assert len(dikenali) >= 0.5 * len(daftar)


def test_contoh_nyata_dari_server():
    """Tiga jawaban salah yang dilaporkan panitia, terhadap FAQ yang terpilih."""
    p, ids = _penjaga_data_nyata()

    def faq(awal):
        return next(i for k, i in ids.items() if k.startswith(awal))

    assert p.tolak("apa resep nasi goreng?", faq("apa perbedaan ukt dan ipi"))
    assert p.tolak("berapa jumlah lulusan", faq("bagaimana ubb menentukan kelompok ukt"))


class ModelUkt:
    """Arah vektor ditentukan kata kunci: UKT, wisuda, atau lainnya.

    Meniru pertanyaan lanjutan: "berapa jumlah lulusan" sendirian tidak cocok
    dengan FAQ mana pun, tetapi begitu disambung konteks sesi ("... kelompok
    UKT ...") skornya 1 terhadap FAQ UKT.
    """

    def encode(self, teks, **_):
        def arah(t):
            if "uang kuliah tunggal" in t:
                return [1.0, 0.0, 0.0]
            if "wisuda" in t:
                return [0.0, 1.0, 0.0]
            return [0.0, 0.0, 1.0]
        return np.array([arah(t) for t in teks], dtype=np.float32)


ENTRI_UKT = [e for e in ENTRI if e["faq_id"] in (1, 2)] + [
    {"faq_id": 5, "teks": "jadwal wisuda dan jumlah lulusan"},
    {"faq_id": 5, "teks": "kapan wisuda lulusan"},
]


def _engine_ukt():
    from retrieval.text import normalize
    m = ModelUkt()
    vek = m.encode([normalize(e["teks"]) for e in ENTRI_UKT])
    snap = Snapshot(versi=1, vektor=vek, pemilik=[e["faq_id"] for e in ENTRI_UKT], dim=3)
    e = Engine(m, snap, tau_high=0.72, tau_low=0.60)
    e.penjaga = PenjagaDomain(ENTRI_UKT)
    return e


def _meta_ukt(ids):
    return {i: {"pertanyaan": f"faq {i}", "jawaban": f"jawaban {i}"} for i in ids}


def test_lanjutan_tidak_nyambung_tidak_diselamatkan_konteks():
    """Kasus nyata: "berapa jumlah lulusan" setelah bertanya kelompok UKT."""
    k = _engine_ukt().jawab("berapa jumlah lulusan", _meta_ukt,
                            konteks="Bagaimana UBB menentukan kelompok UKT?",
                            faq_sebelumnya=2)
    assert k.tipe != Tipe.JAWABAN


def test_lanjutan_yang_nyambung_tetap_dijawab():
    k = _engine_ukt().jawab("kalau biayanya?", _meta_ukt,
                            konteks="Bagaimana UBB menentukan kelompok UKT?",
                            faq_sebelumnya=2)
    assert k.tipe == Tipe.JAWABAN
    assert k.faq_id == 1
