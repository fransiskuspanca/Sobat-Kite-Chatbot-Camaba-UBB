"""Normalisasi teks — SALINAN VERBATIM dari notebook Colab (sel 4a).

⚠️  JANGAN MERAPIKAN FILE INI.

Normalisasi saat membangun index wajib sama persis dengan saat runtime.
Beda satu karakter membuat vektor query dan vektor dokumen berada di ruang
yang sedikit berbeda — akurasi turun tanpa satu pun error muncul. Jenis bug
yang paling sulit dilacak.

Sumber: NLP_Chatbot_Camaba_UBB_2026.ipynb, sel "4a. Normalisasi teks".
Pagar pengaman: tests/test_normalisasi.py terhadap artifacts/normalisasi_gold.json.
"""

import re
import unicodedata

# ---------------------------------------------------------------
# 4a. Normalisasi teks (konservatif)
# ---------------------------------------------------------------
SINGKATAN = {
    r"\bubb\b":       "universitas bangka belitung",
    r"\bpmb\b":       "penerimaan mahasiswa baru",
    r"\bprodi\b":     "program studi",
    r"\bti\b":        "teknologi informasi",
    r"\bfak\b":       "fakultas",
    r"\bukt\b":       "uang kuliah tunggal",
    r"\bmaba\b":      "mahasiswa baru",
    r"\bcamaba\b":    "calon mahasiswa baru",
    r"\bakre\b":      "akreditasi",
    r"\bkampus\s*kite\b": "universitas bangka belitung",
}
# Slang -> baku (arah kebalikan dipakai untuk augmentasi)
SLANG = {
    r"\bgak\b": "tidak", r"\bnggak\b": "tidak", r"\bga\b": "tidak", r"\bengga\b": "tidak",
    r"\bgimana\b": "bagaimana", r"\bgmn\b": "bagaimana", r"\bbgmn\b": "bagaimana",
    r"\bbrp\b": "berapa", r"\bkpn\b": "kapan", r"\bdmn\b": "dimana",
    r"\byg\b": "yang", r"\bdgn\b": "dengan", r"\bsy\b": "saya",
    r"\bkak\b": "", r"\bmin\b": "", r"\bbang\b": "", r"\bkk\b": "",
}


def normalize(text, expand=True):
    """Normalisasi ringan. expand=True juga membakukan slang & singkatan."""
    t = unicodedata.normalize("NFKC", str(text)).lower()
    t = re.sub(r"http\S+", " ", t)
    t = re.sub(r"[^\w\s\-\?]", " ", t)          # tanda tanya dipertahankan (sinyal intent)
    if expand:
        for pat, rep in {**SLANG, **SINGKATAN}.items():
            t = re.sub(pat, rep, t)
    return re.sub(r"\s+", " ", t).strip()
