"""Paket data tambahan dari GitHub -> basis data, tanpa menyentuh server.

Hasil simulasi pertanyaan camaba dicatat sebagai paket JSON kecil di
`data/sinkron/` pada repo, didaftar di `data/sinkron/daftar.json`. Server
mengambilnya lewat cron (`manage.py sinkron_data`), menerapkan paket yang
belum pernah diterapkan, lalu reindex dengan regression gate biasa.

Bentuk paket:

    {
      "keterangan": "Simulasi camaba jalur mandiri",
      "variasi": {"Pertanyaan kanonik": ["cara bertanya lain", ...]},
      "faq_baru": [
        {"pertanyaan": "...", "jawaban": "...", "kategori": "...",
         "sub_kategori": "...", "sumber": "...", "butuh_verifikasi": true,
         "variasi": ["...", ...]}
      ]
    }

Paket hanya MENAMBAH: jawaban FAQ yang sudah ada tidak pernah ditimpa,
supaya suntingan panitia di admin aman. FAQ baru tanpa kunci
"butuh_verifikasi" dianggap belum disetujui (jawabannya diganti pesan
eskalasi sampai verifikator menyetujuinya di admin).
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from faq.models import Faq, FaqVariasi

BERKAS_DAFTAR = "daftar.json"
BATAS_WAKTU = 30


def _norm(teks) -> str:
    return " ".join(str(teks or "").lower().split())


def baca(sumber: str, nama: str) -> bytes:
    """Ambil `nama` dari URL (diakhiri /) atau folder lokal."""
    if sumber.startswith(("http://", "https://")):
        url = sumber.rstrip("/") + "/" + nama
        with urllib.request.urlopen(url, timeout=BATAS_WAKTU) as r:
            return r.read()
    return (Path(sumber) / nama).read_bytes()


def path_status() -> Path:
    return Path(settings.ARTIFACTS_DIR) / "sinkron_diterapkan.json"


def muat_status() -> dict:
    p = path_status()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def simpan_status(status: dict) -> None:
    p = path_status()
    p.parent.mkdir(parents=True, exist_ok=True)
    sementara = p.with_suffix(".tmp")
    sementara.write_text(json.dumps(status, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    sementara.replace(p)


@dataclass
class HasilPaket:
    faq_baru: int = 0
    variasi_baru: int = 0
    peringatan: list = field(default_factory=list)

    def ringkas(self) -> str:
        return f"{self.faq_baru} FAQ baru, {self.variasi_baru} variasi baru"


def terapkan_paket(data: dict, terlarang: set[str] = frozenset()) -> HasilPaket:
    """Terapkan satu paket dalam satu transaksi.

    `terlarang` berisi teks (ternormalisasi) yang tidak boleh menjadi variasi,
    yaitu soal hard eval: menambahkannya membuat regression gate tidak jujur.
    """
    if not isinstance(data, dict):
        raise ValueError("Paket harus berupa objek JSON")
    hasil = HasilPaket()

    with transaction.atomic():
        faq_per_teks = {_norm(f.pertanyaan): f for f in Faq.objects.all()}
        # Teks yang sudah dipakai FAQ mana pun: menambahkannya ke FAQ lain
        # membuat dua jawaban berebut satu pertanyaan.
        terpakai = set(faq_per_teks)
        terpakai |= {_norm(t) for t in FaqVariasi.objects.values_list("teks", flat=True)}

        def tambah_variasi(faq, daftar):
            for teks in daftar or []:
                teks = " ".join(str(teks or "").split())
                n = _norm(teks)
                if not teks or n in terpakai:
                    continue
                if n in terlarang:
                    hasil.peringatan.append(f"variasi = soal hard eval, dilewati: {teks[:60]}")
                    continue
                FaqVariasi.objects.create(faq=faq, teks=teks, asal="augmentasi")
                terpakai.add(n)
                hasil.variasi_baru += 1

        for r in data.get("faq_baru") or []:
            tanya = " ".join(str(r.get("pertanyaan") or "").split())
            jawab = str(r.get("jawaban") or "").strip()
            if not tanya or not jawab:
                hasil.peringatan.append(f"FAQ baru tanpa pertanyaan/jawaban: {tanya[:60]!r}")
                continue
            faq = faq_per_teks.get(_norm(tanya))
            if faq is None:
                from faq.management.commands.import_colab import (
                    _pisah_sumber, flag_butuh_verifikasi)
                label, url = _pisah_sumber(r.get("sumber", ""))
                faq = Faq.objects.create(
                    pertanyaan=tanya, jawaban=jawab,
                    kategori=str(r.get("kategori") or "")[:120],
                    sub_kategori=str(r.get("sub_kategori") or "")[:120],
                    sumber_label=label, sumber_url=url,
                    butuh_verifikasi=(bool(r.get("butuh_verifikasi", True))
                                      or flag_butuh_verifikasi(jawab)))
                faq_per_teks[_norm(tanya)] = faq
                terpakai.add(_norm(tanya))
                hasil.faq_baru += 1
            else:
                hasil.peringatan.append(f"FAQ sudah ada, jawaban tidak ditimpa: {tanya[:60]}")
            tambah_variasi(faq, r.get("variasi"))

        for tanya, daftar in (data.get("variasi") or {}).items():
            faq = faq_per_teks.get(_norm(tanya))
            if faq is None:
                hasil.peringatan.append(f"variasi untuk FAQ yang tidak ada: {tanya[:60]}")
                continue
            tambah_variasi(faq, daftar)

    return hasil


def jalankan(sumber: str, terlarang: set[str] = frozenset(), tulis=print) -> int:
    """Terapkan semua paket baru di `sumber`. Kembalikan jumlah perubahan.

    Paket yang sudah diterapkan dilewati. Paket yang gagal dicatat dan baru
    dicoba lagi bila isinya berubah, supaya cron tidak mengulang galat yang
    sama tiap 15 menit.
    """
    daftar = json.loads(baca(sumber, BERKAS_DAFTAR))
    if not isinstance(daftar, list):
        raise ValueError(f"{BERKAS_DAFTAR} harus berupa daftar nama berkas")
    status = muat_status()
    perubahan = 0
    for nama in daftar:
        lama = status.get(nama)
        if lama and lama.get("hasil") == "ok":
            continue
        isi = baca(sumber, nama)
        sidik = hashlib.sha256(isi).hexdigest()
        if lama and lama.get("sha256") == sidik:
            continue
        catatan = {"sha256": sidik, "waktu": timezone.now().isoformat()}
        try:
            h = terapkan_paket(json.loads(isi), terlarang)
        except (ValueError, TypeError, AttributeError) as e:
            catatan.update(hasil="gagal", pesan=str(e)[:300])
            tulis(f"✗ {nama}: {e}")
        else:
            catatan.update(hasil="ok", ringkasan=h.ringkas())
            perubahan += h.faq_baru + h.variasi_baru
            tulis(f"✓ {nama}: {h.ringkas()}")
            for p in h.peringatan[:10]:
                tulis(f"    ⚠️  {p}")
        status[nama] = catatan
        simpan_status(status)
    return perubahan
