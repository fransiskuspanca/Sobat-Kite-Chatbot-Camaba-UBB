"""Rincian regression gate: untuk tiap soal hard_eval, teks mana yang menang.

Jalankan dari APP_DIR (setelah .env dimuat):
    .venv/bin/python manage.py shell < deploy/diagnosa_hard_eval.py

Bedanya dengan `reindex`: semua soal dicetak (bukan 10 pertama), lengkap
dengan teks vektor pemenang — biasanya sebuah variasi yang terlalu umum.
"""
import numpy as np
from django.conf import settings

from faq.actions import kumpulkan_entri
from faq.models import Faq
from faq.services import muat_engine
from retrieval.indexer import muat_hard_eval

engine = muat_engine()
entri, peta = kumpulkan_entri()
vektor = engine.encode([e["teks"] for e in entri], is_query=False)
judul = dict(Faq.objects.values_list("id", "pertanyaan"))
hard = muat_hard_eval(settings.ARTIFACTS_DIR / "hard_eval.json") or {}

benar = total = 0
for kanonik, soal in hard.items():
    emas = peta.get(" ".join(kanonik.lower().split()))
    for q in soal:
        skor = vektor @ engine.encode(q, is_query=True)
        i = int(np.argmax(skor))
        dapat = entri[i]["faq_id"]
        total += 1
        if dapat == emas:
            benar += 1
            print(f"OK  {skor[i]:.3f}  {q!r}")
        else:
            print(f"XX  {skor[i]:.3f}  {q!r}\n      menang : {entri[i]['teks']!r}"
                  f" -> {judul.get(dapat)!r}\n      harusnya: {kanonik!r}")
print(f"\nAcc@1 = {benar}/{total} = {benar / max(total, 1):.3f}")
