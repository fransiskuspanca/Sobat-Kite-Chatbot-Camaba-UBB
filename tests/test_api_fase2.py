"""Tes API Fase 2 — empat tier, CORS, rate limit, log, health.

Memakai engine tiruan supaya tidak memuat model 600 MB: yang diuji di sini
adalah lapisan HTTP, bukan kualitas retrieval (itu sudah diuji terpisah di
tests/test_engine.py dan tests/test_tiers.py).
"""

import json
from datetime import date

import numpy as np
import pytest
from django.test import Client, override_settings

from faq.models import Faq
from percakapan.models import ChatLog, Feedback
from retrieval.engine import Engine, Snapshot
from tests.test_engine import ModelTiruan

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_api")]

URL_QUERY = "/v1/chat/query"
URL_FEEDBACK = "/v1/chat/feedback"
URL_HEALTH = "/v1/chat/health"


@pytest.fixture
def kb():
    """Tiga FAQ: normal, belum terverifikasi, dan bersumber."""
    a = Faq.objects.create(
        pertanyaan="apa itu universitas bangka belitung",
        jawaban="PTN di Bangka Belitung.", kategori="A. Umum",
        sumber_label="Profil UBB",
        terakhir_diverifikasi=date(2026, 1, 15))
    b = Faq.objects.create(
        pertanyaan="berapa luas kampus",
        jawaban="Perlu wawancara. (Belum ada angka resmi.)",
        kategori="A. Umum", butuh_verifikasi=True)
    c = Faq.objects.create(
        pertanyaan="berapa uang kuliah tunggal",
        jawaban="Bervariasi per prodi.", sumber_url="https://ubb.ac.id/ukt")
    return {"normal": a, "belum": b, "ukt": c}


@pytest.fixture
def engine_tiruan(kb, monkeypatch):
    """Pasang engine berbasis ModelTiruan ke jalur yang dipakai router."""
    model = ModelTiruan()
    daftar = list(Faq.objects.order_by("id"))
    vek = model.encode([f.pertanyaan for f in daftar])
    snap = Snapshot(versi=7, vektor=vek.astype(np.float32),
                    pemilik=[f.id for f in daftar], dim=ModelTiruan.DIM)
    eng = Engine(model, snap, tau_high=0.72, tau_low=0.60)

    import faq.services as svc
    monkeypatch.setattr(svc, "engine_siap", lambda: eng)
    import api.router as router_mod
    monkeypatch.setattr(router_mod, "__engine_uji", eng, raising=False)
    return eng


@pytest.fixture(autouse=True)
def bersihkan_cache():
    """Rate limit memakai cache — jangan sampai bocor antar-tes."""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


def tanya(client, q, **kw):
    body = {"query": q, **kw}
    return client.post(URL_QUERY, json.dumps(body),
                       content_type="application/json")


# --- empat tier ----------------------------------------------------------

def test_tier_jawaban(client, engine_tiruan, kb):
    r = tanya(client, "apa itu universitas bangka belitung")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["tipe"] == "jawaban"
    # Prinsip #1: isi datang APA ADANYA dari basis data.
    assert d["jawaban"].startswith("PTN di Bangka Belitung.")


def test_tier_sapaan(client, engine_tiruan):
    d = tanya(client, "halo").json()["data"]
    assert d["tipe"] == "sapaan"
    assert d["answer_id"] is None


def test_tier_fallback_di_luar_domain(client, engine_tiruan):
    """Definition of done Fase 2 menyebut ini secara khusus."""
    d = tanya(client, "resep rendang padang enak").json()["data"]
    assert d["tipe"] == "fallback"
    assert "Maaf" in d["jawaban"]


def test_tier_eskalasi_menyembunyikan_jawaban(client, engine_tiruan, kb):
    """Prinsip #4 harus berlaku di API, bukan cuma di engine."""
    d = tanya(client, "berapa luas kampus").json()["data"]
    assert d["tipe"] == "eskalasi"
    assert "Perlu wawancara" not in d["jawaban"]
    assert "Panitia PMB" in d["jawaban"]
    # tetap dapat diaudit
    assert d["answer_id"] == kb["belum"].id


# --- jejak audit (prinsip #2) -------------------------------------------

def test_response_menyertakan_jejak_audit(client, engine_tiruan, kb):
    d = tanya(client, "apa itu universitas bangka belitung").json()["data"]
    assert d["answer_id"] == kb["normal"].id
    assert d["sumber"] == "Profil UBB"
    assert d["terakhir_diverifikasi"] == "2026-01-15"
    assert d["index_version"] == 7
    assert d["log_id"]
    assert isinstance(d["latency_ms"], int)


def test_sumber_url_diprioritaskan(client, engine_tiruan, kb):
    d = tanya(client, "berapa uang kuliah tunggal").json()["data"]
    assert d["sumber"] == "https://ubb.ac.id/ukt"


# --- pencatatan log ------------------------------------------------------

def test_setiap_query_tercatat(client, engine_tiruan):
    tanya(client, "apa itu universitas bangka belitung", session_id="sesi-1")
    assert ChatLog.objects.count() == 1
    log = ChatLog.objects.first()
    assert log.session_id == "sesi-1"
    assert log.index_version == 7
    assert log.latency_ms >= 0


def test_fallback_tercatat_untuk_antrean_konten(client, engine_tiruan):
    """Log fallback -> antrean konten -> panitia menambah FAQ."""
    tanya(client, "resep rendang padang enak")
    assert ChatLog.objects.filter(tipe="fallback").count() == 1


def test_log_gagal_tidak_menggagalkan_jawaban(client, engine_tiruan, monkeypatch):
    """Prinsip #6: camaba tetap dapat jawaban walau pencatatan gagal."""
    from django.db import DatabaseError

    import api.router as mod

    def meledak(**kw):
        raise DatabaseError("db mati")

    # Ganti _catat_log agar benar-benar melempar dari dalam handler.
    asli = mod._catat_log
    monkeypatch.setattr(mod, "_catat_log", meledak)
    try:
        r = tanya(client, "apa itu universitas bangka belitung")
    finally:
        monkeypatch.setattr(mod, "_catat_log", asli)

    # Camaba TETAP menerima jawabannya — pencatatan log yang gagal tidak
    # boleh merampas jawaban yang sudah siap.
    assert r.status_code == 200
    assert r.json()["data"]["tipe"] == "jawaban"
    assert "db mati" not in r.content.decode()


# --- validasi input ------------------------------------------------------

def test_query_terlalu_panjang_ditolak(client, engine_tiruan):
    r = tanya(client, "x" * 501)
    assert r.status_code == 422
    assert r.json()["sukses"] is False


def test_query_kosong_ditolak(client, engine_tiruan):
    assert tanya(client, "").status_code == 422


def test_query_500_karakter_diterima(client, engine_tiruan):
    assert tanya(client, "a" * 500).status_code == 200


# --- feedback ------------------------------------------------------------

def test_feedback_tersimpan(client, engine_tiruan):
    lid = tanya(client, "apa itu universitas bangka belitung").json()["data"]["log_id"]
    r = client.post(URL_FEEDBACK,
                    json.dumps({"log_id": lid, "rating": "up",
                                "komentar": "membantu"}),
                    content_type="application/json")
    assert r.status_code == 200
    assert Feedback.objects.get(log_id=lid).rating == "up"


def test_feedback_log_id_tak_dikenal(client, engine_tiruan):
    r = client.post(URL_FEEDBACK,
                    json.dumps({"log_id": "hantu", "rating": "up"}),
                    content_type="application/json")
    assert r.status_code == 404


def test_feedback_rating_invalid(client, engine_tiruan):
    lid = tanya(client, "halo").json()["data"]["log_id"]
    r = client.post(URL_FEEDBACK,
                    json.dumps({"log_id": lid, "rating": "bagus"}),
                    content_type="application/json")
    assert r.status_code == 422


def test_feedback_bisa_diperbarui(client, engine_tiruan):
    lid = tanya(client, "halo").json()["data"]["log_id"]
    for rating in ("up", "down"):
        client.post(URL_FEEDBACK, json.dumps({"log_id": lid, "rating": rating}),
                    content_type="application/json")
    assert Feedback.objects.count() == 1
    assert Feedback.objects.get(log_id=lid).rating == "down"


# --- health --------------------------------------------------------------

def test_health_siap(client, engine_tiruan):
    r = client.get(URL_HEALTH)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "ok" and d["model_siap"] is True
    assert d["index_version"] == 7


def test_health_503_saat_model_belum_siap(client, monkeypatch):
    import faq.services as svc
    monkeypatch.setattr(svc, "engine_siap", lambda: None)
    r = client.get(URL_HEALTH)
    assert r.status_code == 503
    assert r.json()["data"]["status"] == "degraded"


def test_healthz_tidak_menyentuh_model(client, monkeypatch):
    """Cek ringan untuk Nginx — harus tetap 200 walau model mati."""
    import faq.services as svc

    def jangan_dipanggil():
        raise AssertionError("healthz tidak boleh menyentuh model")

    monkeypatch.setattr(svc, "engine_siap", jangan_dipanggil)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# --- prinsip #6: model mati, layanan hidup ------------------------------

def test_model_mati_tetap_menjawab_sopan(client, monkeypatch):
    import faq.services as svc
    monkeypatch.setattr(svc, "engine_siap", lambda: None)

    r = tanya(client, "apa itu ubb")
    assert r.status_code == 200          # bukan 500
    d = r.json()["data"]
    assert d["tipe"] == "fallback"
    assert "Maaf" in d["jawaban"]


def test_engine_meledak_tidak_bocorkan_traceback(client, engine_tiruan,
                                                 monkeypatch):
    import faq.services as svc

    def meledak():
        raise RuntimeError("rahasia internal")

    monkeypatch.setattr(svc, "engine_siap", meledak)
    r = tanya(client, "apa itu ubb")
    assert r.status_code == 503
    assert "rahasia internal" not in r.content.decode()


# --- rate limit ----------------------------------------------------------

def test_rate_limit_menolak_setelah_batas(client, engine_tiruan):
    from api.throttle import BATAS_PER_MENIT

    kode = [tanya(client, "halo").status_code
            for _ in range(BATAS_PER_MENIT + 5)]
    assert 429 in kode
    assert kode[0] == 200


def test_rate_limit_per_ip_bukan_global(client, engine_tiruan):
    """Tanpa X-Forwarded-For semua terlihat dari satu IP dan SELURUH
    pengguna terblokir sekaligus."""
    from api.throttle import BATAS_PER_MENIT

    for _ in range(BATAS_PER_MENIT + 5):
        tanya(client, "halo", **{})
    # IP berbeda harus tetap dilayani
    r = client.post(URL_QUERY, json.dumps({"query": "halo"}),
                    content_type="application/json",
                    HTTP_X_FORWARDED_FOR="203.0.113.9")
    assert r.status_code == 200


def test_ambil_ip_memakai_x_forwarded_for():
    from django.test import RequestFactory

    from api.throttle import ambil_ip

    req = RequestFactory().post("/", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1")
    assert ambil_ip(req) == "203.0.113.9"


# --- CORS ----------------------------------------------------------------

def test_preflight_dari_pmb_diizinkan(client):
    r = client.options(URL_QUERY, HTTP_ORIGIN="https://pmb.ubb.ac.id",
                       HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert r.headers.get("access-control-allow-origin") == "https://pmb.ubb.ac.id"


def test_origin_asing_tidak_diizinkan(client):
    r = client.options(URL_QUERY, HTTP_ORIGIN="https://situs-asing.example",
                       HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert "access-control-allow-origin" not in r.headers


def test_cors_tidak_mengizinkan_semua_origin():
    from django.conf import settings
    assert getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False) is False
    assert "https://pmb.ubb.ac.id" in settings.CORS_ALLOWED_ORIGINS


def test_cors_tanpa_kredensial():
    from django.conf import settings
    assert settings.CORS_ALLOW_CREDENTIALS is False


# --- permukaan serangan --------------------------------------------------

def test_admin_tidak_terjangkau_dari_urlconf_api(client):
    """Proses API tidak memuat /admin/* sama sekali (Bagian 3)."""
    assert client.get("/admin/").status_code == 404


# --- tier identitas ------------------------------------------------------

def test_tier_identitas_menjawab_siapa_kamu(client, engine_tiruan, kb):
    """Sebelum tier ini, "siapa kamu?" jatuh ke fallback."""
    d = tanya(client, "siapa kamu?").json()["data"]
    assert d["tipe"] == "identitas"
    assert "SOBAT KITE" in d["jawaban"]


def test_identitas_mengikuti_pengaturan_admin(client, engine_tiruan, kb):
    from faq.models import PengaturanSapaan

    p = PengaturanSapaan.ambil()
    p.nama_bot = "SI PANDU"
    p.peran_bot = "Asisten PMB"
    p.save()

    d = tanya(client, "kamu siapa").json()["data"]
    assert "SI PANDU" in d["jawaban"]
    assert "Asisten PMB" in d["jawaban"]


def test_identitas_tidak_menyerobot_pertanyaan_lain(client, engine_tiruan, kb):
    """"siapa rektor UBB" adalah pertanyaan konten, bukan tentang chatbot."""
    for q in ("siapa rektor ubb", "siapa saya", "berapa biaya kuliah"):
        d = tanya(client, q).json()["data"]
        assert d["tipe"] != "identitas", q


def test_identitas_tercatat_di_log(client, engine_tiruan, kb):
    """Bukan fallback — jangan mengotori antrean konten panitia."""
    tanya(client, "siapa kamu?")
    assert ChatLog.objects.filter(tipe="identitas").count() == 1
    assert ChatLog.objects.filter(tipe="fallback").count() == 0


def test_fallback_menyebut_pertanyaan_camaba(client, engine_tiruan, kb):
    """Di luar konteks: jawaban menyebut ulang inti pertanyaan."""
    d = tanya(client, "siapa prabowo subianto").json()["data"]
    assert d["tipe"] == "fallback"
    assert "prabowo subianto" in d["jawaban"]


def test_fallback_mengikuti_pengaturan_admin(client, engine_tiruan, kb):
    from faq.models import PengaturanSapaan

    p = PengaturanSapaan.ambil()
    p.fallback_template = "Wah, {kunci} di luar cakupan saya ya."
    p.save()

    d = tanya(client, "warna gedung telkom").json()["data"]
    assert d["jawaban"] == "Wah, warna gedung telkom di luar cakupan saya ya."
