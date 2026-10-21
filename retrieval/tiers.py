"""Keputusan jawab / klarifikasi / eskalasi / fallback.

Port dari ChatbotCamaba.jawab() di notebook (sel 10), dipisah dari model dan
dari Django supaya bisa diuji tanpa memuat 600 MB bobot dan tanpa basis data.

Modul ini TIDAK mengimpor faq/ maupun api/ (lihat Bagian 5 dokumen rencana).
Ia menerima kandidat + metadata, mengembalikan keputusan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Tipe(StrEnum):
    JAWABAN = "jawaban"
    KLARIFIKASI = "klarifikasi"
    ESKALASI = "eskalasi"
    FALLBACK = "fallback"
    SAPAAN = "sapaan"
    IDENTITAS = "identitas"
    KOSONG = "kosong"


# --- Teks tetap — VERBATIM dari notebook sel 10 --------------------------

SAPAAN = {
    r"^(hai|halo|hallo|hi|pagi|siang|sore|malam|assalam\w*|permisi)\b":
        "Halo! 👋 Saya asisten informasi penerimaan mahasiswa baru Universitas "
        "Bangka Belitung. Ada yang bisa saya bantu seputar jalur masuk, biaya "
        "kuliah, program studi, atau beasiswa?",
    r"^(terima kasih|makasih|thanks|tengkyu|oke|ok|siap)\b":
        "Sama-sama! Semoga sukses masuk UBB 🎓 Ada lagi yang ingin ditanyakan?",
    r"^(dadah|bye|sampai jumpa|selamat tinggal)\b":
        "Sampai jumpa! Semoga berhasil di seleksi PMB UBB.",
}

# Pertanyaan tentang chatbot itu sendiri: "siapa kamu", "kamu bisa apa".
# Sebelum ada tier ini pertanyaan seperti itu jatuh ke fallback — chatbot
# terkesan tidak mengenali dirinya sendiri.
IDENTITAS = [
    r"\b(siapa|sapa)\s*(kah)?\s*(kamu|kau|anda|km|situ|ini)\b",
    r"\b(kamu|anda|km)\s*(itu)?\s*siapa\b",
    r"\bnama\s*(kamu|anda|km|nya)\b",
    r"\bkenal\w*\s*(diri|dirimu)\b",
    r"\b(kamu|anda|km)\s*(ini)?\s*(robot|bot|manusia|ai)\b",
    r"\b(kamu|anda|km)\s*(bisa|dapat)\s*(apa|ngapain)\b",
    r"\bbisa\s*(bantu\s*)?apa\s*(aja|saja)?\b",
]

PESAN_ESKALASI = (
    "Untuk pertanyaan ini saya belum punya data resmi yang terverifikasi, dan "
    "saya tidak ingin memberi informasi yang keliru.\n\n"
    "Silakan hubungi Panitia PMB UBB secara langsung:\n"
    "🌐 https://www.ubb.ac.id\n"
    "📧 Bagian Akademik & Kemahasiswaan UBB"
)

PESAN_FALLBACK = (
    "Maaf, saya belum memahami pertanyaan Anda. 🙏\n\n"
    "Saya khusus melayani informasi seputar penerimaan mahasiswa baru UBB — "
    "misalnya jalur masuk (SNBP/SNBT/Mandiri), biaya kuliah, program studi, "
    "beasiswa, asrama, dan fasilitas kampus.\n\n"
    "Coba tanyakan dengan kalimat lain, atau hubungi https://www.ubb.ac.id"
)

# Prinsip #6: model boleh mati, layanan tidak.
PESAN_LAYANAN_SIBUK = (
    "Maaf, layanan sedang sibuk. 🙏 Silakan coba lagi sesaat lagi, atau "
    "hubungi Panitia PMB UBB di https://www.ubb.ac.id"
)

PESAN_KOSONG = "Silakan ketik pertanyaan Anda."

# --- Kunci pertanyaan untuk fallback ------------------------------------
# Fallback yang menyebut ulang apa yang ditanyakan terasa jauh lebih nyambung
# ("Maaf, saya tidak dapat memberikan informasi tentang prabowo subianto")
# daripada kalimat generik. Yang disebut ulang BUKAN query mentah, melainkan
# intinya — kata tanya dan basa-basi di depan dibuang.
STOPWORD_AWAL = {
    "apa", "apakah", "siapa", "sapa", "kapan", "dimana", "di", "mana",
    "bagaimana", "gimana", "kenapa", "mengapa", "berapa", "adakah",
    "bisakah", "tolong", "mohon", "maaf", "permisi", "info", "informasi",
    "tentang", "soal", "mengenai", "seputar", "itu", "yang", "ya", "dong",
    "kah", "sih", "nya", "yg", "gmn", "gmna",
}

# Kunci dipakai kembali di dalam kalimat, jadi tanda baca dibuang: query
# "<script>" tidak boleh muncul utuh di jawaban. Tanda hubung dipertahankan
# supaya "non-reguler" tidak pecah.
_TANDA_BACA = re.compile(r"[^\w\s\-]", re.UNICODE)
_SPASI = re.compile(r"\s+")

KUNCI_KATA_MAKS = 8
KUNCI_CHAR_MAKS = 60


def kunci_pertanyaan(teks: str, kata_maks: int = KUNCI_KATA_MAKS,
                     char_maks: int = KUNCI_CHAR_MAKS) -> str:
    """Inti pertanyaan camaba, aman untuk disisipkan ke kalimat jawaban.

    Mengembalikan "" kalau tidak ada yang tersisa untuk disebut (query berisi
    tanda baca semua, atau kata tanya semua) — pemanggil harus memakai kalimat
    tanpa penyebutan untuk kasus itu.
    """
    t = _TANDA_BACA.sub(" ", teks or "")
    t = _SPASI.sub(" ", t).strip()
    if not t:
        return ""

    kata = t.split(" ")
    # Buang kata tanya/basa-basi di DEPAN saja. "siapa" di tengah kalimat
    # ("nomor siapa") masih bagian dari inti pertanyaan.
    while kata and kata[0].lower() in STOPWORD_AWAL:
        kata.pop(0)
    # Habis semua ("apa itu ya") — pakai kalimat aslinya daripada kosong.
    if not kata:
        kata = t.split(" ")

    dipotong = len(kata) > kata_maks
    kata = kata[:kata_maks]
    hasil = " ".join(kata)
    if len(hasil) > char_maks:
        hasil = hasil[:char_maks].rsplit(" ", 1)[0]
        dipotong = True
    return hasil + "…" if dipotong else hasil


def rakit_fallback(query: str, template: str = "", tanpa_kunci: str = "") -> str:
    """Kalimat fallback yang menyebut ulang inti pertanyaan camaba.

    `template` memakai placeholder {kunci} dan berasal dari pengaturan admin;
    kalau kosong, PESAN_FALLBACK lama dipakai supaya perilaku tidak berubah
    pada instalasi yang belum mengisinya.
    """
    if not template:
        return PESAN_FALLBACK
    kunci = kunci_pertanyaan(query)
    if not kunci:
        # Tidak ada yang bisa disebut ulang; "informasi tentang ." janggal.
        return tanpa_kunci or PESAN_FALLBACK
    try:
        return template.format(kunci=kunci)
    except (KeyError, IndexError, ValueError):
        # Panitia menulis placeholder yang tidak dikenal — jangan sampai
        # seluruh endpoint gagal hanya karena salah ketik di admin.
        return PESAN_FALLBACK

# --- Pertanyaan lanjutan ----------------------------------------------
# "apa saja?", "kalo prodinya?", "syaratnya gimana?" hanya bermakna bila
# disambung dengan pertanyaan sebelumnya. Yang dianggap lanjutan: pendek,
# atau dibuka kata penyambung.
KATA_LANJUTAN_MAKS = 5
_PEMBUKA_LANJUTAN = re.compile(
    r"^(kalau|kalo|klo|klw|kl|terus|trus|trs|lalu|lantas|terus kalau|"
    r"bagaimana dengan|gimana dengan|gmn dengan|selain itu|dan|sama)\b")


def tampak_lanjutan(teks: str) -> bool:
    """Apakah `teks` tampak seperti pertanyaan lanjutan yang tidak utuh?"""
    t = (teks or "").lower().strip()
    kata = re.findall(r"\w+", t)
    if not kata:
        return False
    return len(kata) <= KATA_LANJUTAN_MAKS or bool(_PEMBUKA_LANJUTAN.match(t))


PANJANG_MAKS = 500   # sejalan dengan client_max_body_size di Nginx


@dataclass(frozen=True)
class Kandidat:
    """Satu hasil pencarian. Sengaja memakai tipe primitif, bukan model Django."""
    faq_id: int
    pertanyaan: str
    skor: float
    jawaban: str = ""
    kategori: str = ""
    sumber_label: str = ""
    sumber_url: str = ""
    butuh_verifikasi: bool = False
    terakhir_diverifikasi: str | None = None


@dataclass
class Keputusan:
    tipe: Tipe
    jawaban: str
    skor: float
    faq_id: int | None = None
    matched: str | None = None
    kategori: str | None = None
    sumber_label: str = ""
    sumber_url: str = ""
    terakhir_diverifikasi: str | None = None
    kandidat: list[dict] = field(default_factory=list)


def cek_sapaan(teks: str) -> str | None:
    t = teks.lower().strip()
    for pat, resp in SAPAAN.items():
        if re.match(pat, t):
            return resp
    return None


def cek_identitas(teks: str) -> bool:
    """Apakah camaba sedang menanyakan chatbot-nya sendiri?

    Memakai `search`, bukan `match` seperti sapaan: pertanyaan identitas sering
    muncul di tengah kalimat ("maaf, siapa kamu ya?").
    """
    t = teks.lower().strip()
    return any(re.search(pat, t) for pat in IDENTITAS)


def _ringkas(kandidat: list[Kandidat]) -> list[dict]:
    return [{"id": k.faq_id, "pertanyaan": k.pertanyaan, "skor": round(k.skor, 4)}
            for k in kandidat]


def putuskan(query: str, kandidat: list[Kandidat], tau_high: float,
             tau_low: float, pesan_identitas: str = "",
             template_fallback: str = "", fallback_tanpa_kunci: str = "",
             luar_domain: bool = False, tidak_nyambung: bool = False) -> Keputusan:
    """Terapkan empat tier. Murni fungsi — tanpa I/O, tanpa DB, tanpa model.

    `pesan_identitas` dan `template_fallback` disuntikkan dari luar (berasal
    dari pengaturan admin) supaya modul ini tetap tidak mengenal Django.
    Kalau kosong, tier identitas dilewati dan fallback memakai teks tetap —
    perilaku lama dipertahankan.

    `luar_domain` dan `tidak_nyambung` berasal dari penjaga domain
    (retrieval/domain.py). Pertanyaan di luar domain selalu fallback, berapa
    pun skornya; FAQ teratas yang tidak berbagi kata pembeda dengan
    pertanyaan tidak dijawab langsung, tetapi ditawarkan sebagai klarifikasi.
    """
    query = (query or "").strip()

    if len(query) < 2:
        return Keputusan(Tipe.KOSONG, PESAN_KOSONG, 0.0)

    if (s := cek_sapaan(query)):
        return Keputusan(Tipe.SAPAAN, s, 1.0)

    # Didahulukan atas pencarian: "siapa kamu" tidak akan pernah cocok dengan
    # FAQ mana pun, jadi tanpa ini ia selalu berakhir di fallback.
    if pesan_identitas and cek_identitas(query):
        return Keputusan(Tipe.IDENTITAS, pesan_identitas, 1.0)

    if not kandidat:
        return Keputusan(
            Tipe.FALLBACK,
            rakit_fallback(query, template_fallback, fallback_tanpa_kunci),
            0.0)

    atas = kandidat[0]
    ringkas = _ringkas(kandidat)

    # --- Tier 3: di luar domain ---
    if atas.skor < tau_low or luar_domain:
        return Keputusan(
            Tipe.FALLBACK,
            rakit_fallback(query, template_fallback, fallback_tanpa_kunci),
            atas.skor, kandidat=ringkas)

    # --- Tier 2: ambigu -> minta klarifikasi ---
    # Skor tinggi tanpa satu pun kata yang nyambung juga dianggap ambigu:
    # model embedding kecil memberi skor tinggi pada kalimat yang hanya mirip
    # bentuknya ("berapa jumlah lulusan" -> FAQ kelompok UKT).
    if atas.skor < tau_high or tidak_nyambung:
        opsi = "\n".join(f"{i}. {c.pertanyaan}" for i, c in enumerate(kandidat, 1))
        return Keputusan(
            Tipe.KLARIFIKASI,
            f"Sepertinya maksud Anda salah satu ini:\n\n{opsi}\n\n"
            "Silakan pilih nomornya atau ketik ulang lebih spesifik.",
            atas.skor, kandidat=ringkas)

    # --- Tier 1a: yakin, tapi jawabannya belum terverifikasi ---
    # Prinsip #4: jawaban belum terverifikasi TIDAK PERNAH tampil. Entri tetap
    # ada di index supaya niat camaba dikenali, tapi isinya diganti eskalasi.
    if atas.butuh_verifikasi:
        return Keputusan(Tipe.ESKALASI, PESAN_ESKALASI, atas.skor,
                         faq_id=atas.faq_id, matched=atas.pertanyaan,
                         kategori=atas.kategori, kandidat=ringkas)

    # --- Tier 1b: yakin, jawaban dikirim VERBATIM dari basis data ---
    jawaban = atas.jawaban
    sumber = atas.sumber_url or atas.sumber_label
    if sumber and sumber not in {"—", "-"}:
        jawaban += f"\n\n📎 Sumber: {sumber}"

    return Keputusan(Tipe.JAWABAN, jawaban, atas.skor,
                     faq_id=atas.faq_id, matched=atas.pertanyaan,
                     kategori=atas.kategori, sumber_label=atas.sumber_label,
                     sumber_url=atas.sumber_url,
                     terakhir_diverifikasi=atas.terakhir_diverifikasi,
                     kandidat=ringkas)


def keputusan_darurat() -> Keputusan:
    """Dipakai saat model/index tidak tersedia. Prinsip #6: bukan HTTP 500."""
    return Keputusan(Tipe.FALLBACK, PESAN_LAYANAN_SIBUK, 0.0)
