"""Soal hard_eval mana yang dirusak sebuah paket sinkron, dan oleh variasi apa.

Paket diterapkan di dalam transaksi lalu dibatalkan; basis data dan index
aktif tidak berubah. Jalankan dari APP_DIR (setelah .env dimuat):
    PAKET=2026-10-21-10-variatif-umum-prodi.json \\
        .venv/bin/python manage.py shell < deploy/diagnosa_paket.py
"""
import json
import os

import numpy as np
from django.conf import settings
from django.db import transaction

from faq import sinkron
from faq.actions import kumpulkan_entri
from faq.models import Faq
from faq.services import muat_engine
from retrieval.indexer import muat_hard_eval

nama = os.environ["PAKET"]
data = json.loads(sinkron.baca(settings.SINKRON_SUMBER, nama))
engine = muat_engine()
hard = muat_hard_eval(settings.ARTIFACTS_DIR / "hard_eval.json") or {}
soal = [(k, q) for k, qs in hard.items() for q in qs]
qv = engine.encode([q for _, q in soal], is_query=True)


def uji(judul_uji, dari_paket=frozenset()):
    entri, peta = kumpulkan_entri()
    vektor = engine.encode([e["teks"] for e in entri], is_query=False)
    judul = dict(Faq.objects.values_list("id", "pertanyaan"))
    skor = qv @ vektor.T
    gagal = []
    for j, (kanonik, q) in enumerate(soal):
        i = int(np.argmax(skor[j]))
        if entri[i]["faq_id"] != peta.get(" ".join(kanonik.lower().split())):
            gagal.append((q, entri[i]["teks"], judul.get(entri[i]["faq_id"]), kanonik))
    print(f"\n{judul_uji}: Acc@1 = {len(soal) - len(gagal)}/{len(soal)}")
    for q, teks, dapat, kanonik in gagal:
        tanda = "PAKET" if " ".join(teks.lower().split()) in dari_paket else "lama "
        print(f"  [{tanda}] {q!r}\n      menang : {teks!r} -> {dapat!r}\n      harusnya: {kanonik!r}")


uji("Tanpa paket")
terlarang = {sinkron._norm(q) for _, q in soal}
with transaction.atomic():
    sinkron.terapkan_paket(data, terlarang)
    baru = {sinkron._norm(v) for vs in (data.get("variasi") or {}).values() for v in vs}
    baru |= {sinkron._norm(v) for f in data.get("faq_baru") or [] for v in [f["pertanyaan"]] + f.get("variasi", [])}
    uji(f"Dengan {nama}", baru)
    transaction.set_rollback(True)
print("\nBasis data tidak diubah.")
