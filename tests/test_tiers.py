"""Tes logika tier — tanpa Django, tanpa model, tanpa basis data."""

import pytest

from retrieval.tiers import (PESAN_ESKALASI, PESAN_FALLBACK, PESAN_KOSONG,
                             Kandidat, Tipe, cek_sapaan, keputusan_darurat,
                             putuskan)

TAU_HIGH, TAU_LOW = 0.72, 0.60


def kand(skor, **kw):
    base = dict(faq_id=1, pertanyaan="Apa itu UBB?", skor=skor,
                jawaban="Universitas Bangka Belitung adalah PTN di Bangka Belitung.",
                kategori="A. Umum")
    base.update(kw)
    return Kandidat(**base)


# --- Tier 1b: jawaban ----------------------------------------------------

def test_skor_tinggi_menjawab_verbatim():
    k = kand(0.91)
    hasil = putuskan("apa itu ubb", [k], TAU_HIGH, TAU_LOW)
    assert hasil.tipe is Tipe.JAWABAN
    # Prinsip #1: jawaban datang APA ADANYA dari basis data, tidak digenerate.
    assert hasil.jawaban.startswith(k.jawaban)
    assert hasil.faq_id == 1
    assert hasil.matched == "Apa itu UBB?"


def test_sumber_dilampirkan():
    hasil = putuskan("apa itu ubb", [kand(0.91, sumber_url="https://ubb.ac.id")], TAU_HIGH, TAU_LOW)
    assert "📎 Sumber: https://ubb.ac.id" in hasil.jawaban


@pytest.mark.parametrize("kosong", ["", "—", "-"])
def test_sumber_placeholder_tidak_dilampirkan(kosong):
    hasil = putuskan("apa itu ubb", [kand(0.91, sumber_label=kosong)], TAU_HIGH, TAU_LOW)
    assert "Sumber" not in hasil.jawaban


def test_url_diprioritaskan_atas_label():
    hasil = putuskan("apa itu ubb", [kand(0.91, sumber_label="Web UBB",
                               sumber_url="https://ubb.ac.id")], TAU_HIGH, TAU_LOW)
    assert "https://ubb.ac.id" in hasil.jawaban


# --- Tier 1a: eskalasi ---------------------------------------------------

def test_butuh_verifikasi_tidak_pernah_menampilkan_jawaban():
    """Prinsip #4 — ini pagar utama terhadap placeholder bocor ke publik."""
    rahasia = "PERLU WAWANCARA dengan bagian akademik"
    hasil = putuskan("apa itu ubb", [kand(0.99, jawaban=rahasia, butuh_verifikasi=True)],
                     TAU_HIGH, TAU_LOW)
    assert hasil.tipe is Tipe.ESKALASI
    assert hasil.jawaban == PESAN_ESKALASI
    assert rahasia not in hasil.jawaban
    # Tetap dapat diaudit (prinsip #2)
    assert hasil.faq_id == 1
    assert hasil.matched == "Apa itu UBB?"


def test_butuh_verifikasi_menang_atas_skor_sempurna():
    hasil = putuskan("apa itu ubb", [kand(1.0, butuh_verifikasi=True)], TAU_HIGH, TAU_LOW)
    assert hasil.tipe is Tipe.ESKALASI


# --- Tier 2: klarifikasi -------------------------------------------------

def test_skor_menengah_minta_klarifikasi():
    kandidat = [kand(0.68), kand(0.65, faq_id=2, pertanyaan="Kapan UBB berdiri?")]
    hasil = putuskan("ubb", kandidat, TAU_HIGH, TAU_LOW)
    assert hasil.tipe is Tipe.KLARIFIKASI
    assert "1. Apa itu UBB?" in hasil.jawaban
    assert "2. Kapan UBB berdiri?" in hasil.jawaban


def test_klarifikasi_tidak_membocorkan_jawaban():
    """Saat ambigu, isi jawaban tidak boleh ikut terkirim."""
    rahasia = "Jawaban rahasia yang belum tentu benar"
    hasil = putuskan("apa itu ubb", [kand(0.65, jawaban=rahasia)], TAU_HIGH, TAU_LOW)
    assert rahasia not in hasil.jawaban


# --- Tier 3: fallback ----------------------------------------------------

def test_skor_rendah_fallback():
    hasil = putuskan("resep rendang", [kand(0.31)], TAU_HIGH, TAU_LOW)
    assert hasil.tipe is Tipe.FALLBACK
    assert hasil.jawaban == PESAN_FALLBACK


def test_tanpa_kandidat_fallback():
    hasil = putuskan("apa pun", [], TAU_HIGH, TAU_LOW)
    assert hasil.tipe is Tipe.FALLBACK


# --- Batas ambang (perilaku di titik persis) -----------------------------

def test_tepat_di_tau_high_menjawab():
    assert putuskan("apa itu ubb", [kand(TAU_HIGH)], TAU_HIGH, TAU_LOW).tipe is Tipe.JAWABAN


def test_tepat_di_tau_low_klarifikasi():
    assert putuskan("apa itu ubb", [kand(TAU_LOW)], TAU_HIGH, TAU_LOW).tipe is Tipe.KLARIFIKASI


def test_sedikit_di_bawah_tau_low_fallback():
    assert putuskan("apa itu ubb", [kand(TAU_LOW - 0.001)], TAU_HIGH, TAU_LOW).tipe is Tipe.FALLBACK


# --- Sapaan & input kosong -----------------------------------------------

@pytest.mark.parametrize("teks", ["halo", "Hai", "HALO", "  pagi  ", "assalamualaikum",
                                  "permisi", "makasih", "terima kasih", "ok", "bye"])
def test_sapaan_dikenali(teks):
    assert cek_sapaan(teks) is not None


@pytest.mark.parametrize("teks", ["", " ", "a", "?"])
def test_input_terlalu_pendek(teks):
    hasil = putuskan(teks, [kand(0.9)], TAU_HIGH, TAU_LOW)
    assert hasil.tipe is Tipe.KOSONG
    assert hasil.jawaban == PESAN_KOSONG


def test_none_aman():
    assert putuskan(None, [], TAU_HIGH, TAU_LOW).tipe is Tipe.KOSONG


def test_sapaan_didahulukan_atas_pencarian():
    """'halo' tidak boleh menembak FAQ mana pun meski skornya tinggi."""
    hasil = putuskan("halo", [kand(0.99)], TAU_HIGH, TAU_LOW)
    assert hasil.tipe is Tipe.SAPAAN


def test_kata_berawalan_sapaan_bukan_sapaan():
    """'oke' cocok, tapi 'okelah kapan pendaftaran' harusnya tetap dicari.

    Notebook memakai \\b sehingga 'siapa' tidak tertangkap oleh pola 'siap'.
    """
    assert cek_sapaan("siapa rektor ubb") is None


# --- Darurat (prinsip #6) ------------------------------------------------

def test_keputusan_darurat_bukan_error():
    hasil = keputusan_darurat()
    assert hasil.tipe is Tipe.FALLBACK
    assert "Maaf" in hasil.jawaban


# --- tier identitas ------------------------------------------------------

def test_cek_identitas_mengenali_berbagai_bentuk():
    from retrieval.tiers import cek_identitas

    for q in ("siapa kamu?", "kamu siapa", "nama kamu siapa",
              "maaf, siapa kamu ya?", "kamu bisa apa", "anda siapa",
              "kamu robot ya?", "bisa bantu apa saja"):
        assert cek_identitas(q), q


def test_cek_identitas_tidak_kebablasan():
    """Pertanyaan konten tidak boleh ikut tertangkap."""
    from retrieval.tiers import cek_identitas

    for q in ("siapa rektor ubb", "siapa saya", "berapa biaya kuliah",
              "siapa yang boleh daftar snbp"):
        assert not cek_identitas(q), q


def test_identitas_dilewati_kalau_pesan_kosong():
    """Tanpa pesan dari admin, perilaku lama dipertahankan."""
    from retrieval.tiers import Tipe, putuskan

    k = putuskan("siapa kamu?", [], 0.72, 0.60, pesan_identitas="")
    assert k.tipe == Tipe.FALLBACK


def test_identitas_didahulukan_atas_pencarian():
    from retrieval.tiers import Kandidat, Tipe, putuskan

    kandidat = [Kandidat(faq_id=1, pertanyaan="apa itu ubb", skor=0.99,
                         jawaban="PTN di Babel.")]
    k = putuskan("siapa kamu?", kandidat, 0.72, 0.60,
                 pesan_identitas="Saya SOBAT KITE.")
    assert k.tipe == Tipe.IDENTITAS
    assert k.jawaban == "Saya SOBAT KITE."


# --- kunci pertanyaan & fallback dinamis ---------------------------------

def test_kunci_membuang_kata_tanya_di_depan():
    from retrieval.tiers import kunci_pertanyaan

    assert kunci_pertanyaan("siapa presiden indonesia?") == "presiden indonesia"
    assert kunci_pertanyaan("apa itu resep rendang") == "resep rendang"
    assert kunci_pertanyaan("warna gedung telkom?") == "warna gedung telkom"


def test_kunci_mempertahankan_kata_tanya_di_tengah():
    """"nomor siapa" — "siapa" di tengah masih bagian dari inti pertanyaan."""
    from retrieval.tiers import kunci_pertanyaan

    assert kunci_pertanyaan("nomor siapa ini") == "nomor siapa ini"


def test_kunci_membuang_tanda_baca():
    """Query dipakai ulang di dalam jawaban; tanda baca tidak boleh lolos."""
    from retrieval.tiers import kunci_pertanyaan

    assert "<" not in kunci_pertanyaan("<script>alert(1)</script>")
    assert ">" not in kunci_pertanyaan("<script>alert(1)</script>")


def test_kunci_kosong_saat_tidak_ada_yang_disebut():
    from retrieval.tiers import kunci_pertanyaan

    assert kunci_pertanyaan("???") == ""
    assert kunci_pertanyaan("   ") == ""
    assert kunci_pertanyaan("") == ""


def test_kunci_dipotong_dengan_elipsis():
    from retrieval.tiers import kunci_pertanyaan

    panjang = "cara main dota 2 biar menang terus dan dapat rank tinggi banget"
    hasil = kunci_pertanyaan(panjang)
    assert hasil.endswith("…")
    assert len(hasil) <= 61


def test_fallback_menyisipkan_kunci():
    from retrieval.tiers import rakit_fallback

    t = "Maaf, saya tidak dapat memberikan informasi tentang {kunci}."
    assert rakit_fallback("prabowo subianto", t) == \
        "Maaf, saya tidak dapat memberikan informasi tentang prabowo subianto."


def test_fallback_tanpa_template_memakai_teks_lama():
    """Instalasi yang belum mengisi admin tidak berubah perilakunya."""
    from retrieval.tiers import PESAN_FALLBACK, rakit_fallback

    assert rakit_fallback("prabowo subianto", "") == PESAN_FALLBACK


def test_fallback_memakai_teks_cadangan_saat_kunci_kosong():
    from retrieval.tiers import rakit_fallback

    t = "Maaf, tentang {kunci}."
    assert rakit_fallback("???", t, "Maaf, saya belum paham.") == \
        "Maaf, saya belum paham."


def test_fallback_placeholder_salah_tidak_meledak():
    """Salah ketik di admin tidak boleh menjatuhkan endpoint."""
    from retrieval.tiers import PESAN_FALLBACK, rakit_fallback

    assert rakit_fallback("prabowo", "Maaf tentang {kata}.") == PESAN_FALLBACK


def test_putuskan_memakai_template_saat_di_luar_domain():
    from retrieval.tiers import Tipe, putuskan

    t = "Maaf, saya tidak dapat memberikan informasi tentang {kunci}."
    k = putuskan("siapa prabowo subianto", [], TAU_HIGH, TAU_LOW,
                 template_fallback=t)
    assert k.tipe is Tipe.FALLBACK
    assert "prabowo subianto" in k.jawaban


def test_putuskan_skor_rendah_juga_memakai_template():
    from retrieval.tiers import Tipe, putuskan

    t = "Maaf, tentang {kunci} saya tidak tahu."
    k = putuskan("warna gedung telkom", [kand(TAU_LOW - 0.01)],
                 TAU_HIGH, TAU_LOW, template_fallback=t)
    assert k.tipe is Tipe.FALLBACK
    assert "warna gedung telkom" in k.jawaban
