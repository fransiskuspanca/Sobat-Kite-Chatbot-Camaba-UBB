"""Tes sesi camaba & riwayat pertanyaan.

Camaba mengisi nama + jenis kelamin lebih dulu, memperoleh session_id, lalu
seluruh pertanyaannya terkumpul di bawah session_id itu dan bisa dipanggil
ulang saat widget dibuka kembali dari localStorage.
"""

import json

import pytest

from percakapan.models import ChatLog, Sesi
from tests.test_api_fase2 import (URL_QUERY, bersihkan_cache, engine_tiruan,  # noqa: F401
                                  kb, tanya)

pytestmark = [pytest.mark.django_db, pytest.mark.urls("config.urls_api")]

URL_SESI = "/v1/chat/session"
URL_RIWAYAT = "/v1/chat/history"


def buat_sesi(client, nama="Budi Santoso", jk="L"):
    return client.post(URL_SESI,
                       json.dumps({"nama_lengkap": nama, "jenis_kelamin": jk}),
                       content_type="application/json")


# --- POST /session -------------------------------------------------------

def test_sesi_mengembalikan_session_id(client):
    r = buat_sesi(client)
    assert r.status_code == 200
    d = r.json()["data"]
    assert len(d["session_id"]) == 32
    assert d["nama_lengkap"] == "Budi Santoso"
    assert d["jenis_kelamin"] == "L"
    assert Sesi.objects.filter(pk=d["session_id"]).exists()


def test_sesi_id_dibuat_server_dan_unik(client):
    a = buat_sesi(client).json()["data"]["session_id"]
    b = buat_sesi(client, "Siti Aminah", "P").json()["data"]["session_id"]
    assert a != b


def test_sesi_menolak_jenis_kelamin_tak_dikenal(client):
    r = client.post(URL_SESI,
                    json.dumps({"nama_lengkap": "Budi", "jenis_kelamin": "X"}),
                    content_type="application/json")
    assert r.status_code == 422
    assert r.json()["sukses"] is False


def test_sesi_menolak_nama_kosong(client):
    r = client.post(URL_SESI,
                    json.dumps({"nama_lengkap": "   ", "jenis_kelamin": "L"}),
                    content_type="application/json")
    assert r.status_code == 422


# --- email camaba (opsional) --------------------------------------------

def test_sesi_menyimpan_email(client):
    r = client.post(URL_SESI,
                    json.dumps({"nama_lengkap": "Budi Santoso",
                                "jenis_kelamin": "L",
                                "email": "budi@example.com"}),
                    content_type="application/json")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["email"] == "budi@example.com"
    assert Sesi.objects.get(pk=d["session_id"]).email == "budi@example.com"


def test_sesi_tanpa_email_tetap_diterima(client):
    """Email opsional — camaba tidak boleh terhalang hanya karena tak mengisi."""
    d = buat_sesi(client).json()["data"]
    assert d["email"] == ""
    assert Sesi.objects.get(pk=d["session_id"]).email == ""


def test_sesi_menolak_email_ngawur(client):
    """Alamat rusak lebih buruk daripada kosong: panitia mengira bisa menghubungi."""
    r = client.post(URL_SESI,
                    json.dumps({"nama_lengkap": "Budi Santoso",
                                "jenis_kelamin": "L",
                                "email": "bukan-email"}),
                    content_type="application/json")
    assert r.status_code == 422
    assert r.json()["sukses"] is False
    assert not Sesi.objects.filter(nama_lengkap="Budi Santoso").exists()


def test_nama_dirapikan(client):
    d = buat_sesi(client, "  Budi   Santoso  ").json()["data"]
    assert d["nama_lengkap"] == "Budi Santoso"


# --- /query membawa session_id ------------------------------------------

def test_query_mengembalikan_session_id(client, engine_tiruan):
    sid = buat_sesi(client).json()["data"]["session_id"]
    r = tanya(client, "apa itu universitas bangka belitung", session_id=sid)
    assert r.status_code == 200
    assert r.json()["data"]["session_id"] == sid


def test_query_tanpa_sesi_tetap_dilayani(client, engine_tiruan):
    """Sesi adalah gerbang di UI, bukan syarat teknis — API tetap menjawab."""
    r = tanya(client, "apa itu universitas bangka belitung")
    assert r.status_code == 200
    assert r.json()["data"]["session_id"] is None


def test_session_id_basi_tidak_menggagalkan_query(client, engine_tiruan):
    r = tanya(client, "apa itu universitas bangka belitung",
              session_id="sesi-yang-sudah-tidak-ada")
    assert r.status_code == 200
    assert r.json()["data"]["session_id"] is None


def test_log_tersambung_ke_sesi(client, engine_tiruan):
    sid = buat_sesi(client).json()["data"]["session_id"]
    tanya(client, "apa itu universitas bangka belitung", session_id=sid)
    log = ChatLog.objects.get(session_id=sid)
    assert log.sesi_id == sid
    assert log.jawaban  # jawaban ikut tersimpan untuk ditampilkan ulang


# --- GET /history --------------------------------------------------------

def test_riwayat_mengumpulkan_pertanyaan_satu_sesi(client, engine_tiruan):
    sid = buat_sesi(client).json()["data"]["session_id"]
    tanya(client, "apa itu universitas bangka belitung", session_id=sid)
    tanya(client, "berapa uang kuliah tunggal", session_id=sid)

    r = client.get(URL_RIWAYAT, {"session_id": sid})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["jumlah"] == 2
    assert d["nama_lengkap"] == "Budi Santoso"
    # Terlama lebih dulu — frontend merender berurutan.
    assert d["riwayat"][0]["query"] == "apa itu universitas bangka belitung"
    assert d["riwayat"][1]["query"] == "berapa uang kuliah tunggal"
    assert d["riwayat"][0]["jawaban"]


def test_riwayat_terpisah_antar_sesi(client, engine_tiruan):
    a = buat_sesi(client, "Budi", "L").json()["data"]["session_id"]
    b = buat_sesi(client, "Siti", "P").json()["data"]["session_id"]
    tanya(client, "apa itu universitas bangka belitung", session_id=a)
    tanya(client, "berapa uang kuliah tunggal", session_id=b)

    ra = client.get(URL_RIWAYAT, {"session_id": a}).json()["data"]
    rb = client.get(URL_RIWAYAT, {"session_id": b}).json()["data"]
    assert ra["jumlah"] == 1 and rb["jumlah"] == 1
    assert ra["riwayat"][0]["query"] != rb["riwayat"][0]["query"]


def test_riwayat_sesi_tak_dikenal_404(client):
    """Frontend perlu tahu localStorage-nya basi supaya meminta identitas lagi."""
    r = client.get(URL_RIWAYAT, {"session_id": "tidak-ada"})
    assert r.status_code == 404
    assert r.json()["sukses"] is False


def test_riwayat_menghormati_batas(client, engine_tiruan):
    sid = buat_sesi(client).json()["data"]["session_id"]
    for _ in range(4):
        tanya(client, "apa itu universitas bangka belitung", session_id=sid)

    d = client.get(URL_RIWAYAT, {"session_id": sid, "limit": 2}).json()["data"]
    assert d["jumlah"] == 2


def test_riwayat_sesi_baru_kosong(client):
    sid = buat_sesi(client).json()["data"]["session_id"]
    d = client.get(URL_RIWAYAT, {"session_id": sid}).json()["data"]
    assert d["jumlah"] == 0
    assert d["riwayat"] == []


# --- kata pengantar pembuka (pengaturan admin) ---------------------------

def test_sambutan_mengikuti_pengaturan(client):
    """Panitia mengubah teks di admin, sambutan camaba ikut berubah."""
    from faq.models import PengaturanSapaan

    p = PengaturanSapaan.ambil()
    p.salam = "Selamat datang"
    p.kalimat = "ada yang bisa kami bantu?"
    p.save()

    r = buat_sesi(client, "Budi Santoso", "L")
    assert r.json()["pesan"] == \
        "Selamat datang Bang Budi Santoso, ada yang bisa kami bantu?"


def test_sapaan_gender_bisa_dimatikan(client):
    from faq.models import PengaturanSapaan

    p = PengaturanSapaan.ambil()
    p.pakai_sapaan_gender = False
    p.save()

    r = buat_sesi(client, "Siti Aminah", "P")
    pesan = r.json()["pesan"]
    assert "Kak" not in pesan
    assert pesan.startswith("Halo Siti Aminah,")


def test_sambutan_default_saat_belum_pernah_diatur(client):
    """Instalasi baru: belum ada baris pengaturan sama sekali."""
    from faq.models import PengaturanSapaan

    PengaturanSapaan.objects.all().delete()
    r = buat_sesi(client, "Budi Santoso", "L")
    assert r.status_code == 200
    assert r.json()["pesan"].startswith("Halo Bang Budi Santoso,")


def test_riwayat_mengirim_pesan_pembuka(client):
    """Widget memakai kalimat yang sama saat sesi lama dibuka ulang."""
    from faq.models import PengaturanSapaan

    p = PengaturanSapaan.ambil()
    p.salam = "Hai"
    p.save()

    sid = buat_sesi(client, "Budi Santoso", "L").json()["data"]["session_id"]
    r = client.get(f"{URL_RIWAYAT}?session_id={sid}")
    assert r.status_code == 200
    assert r.json()["data"]["pesan_pembuka"].startswith("Hai Bang Budi Santoso,")


def test_sesi_mengirim_dua_gelembung_pembuka(client):
    """Camaba disambut sapaan bernama LALU perkenalan chatbot."""
    d = buat_sesi(client, "Budi Santoso", "L").json()["data"]
    assert len(d["pembuka"]) == 2
    assert d["pembuka"][0].startswith("Halo Bang Budi Santoso,")
    assert "SOBAT KITE" in d["pembuka"][1]


def test_pesan_lama_tetap_kalimat_pertama(client):
    """Klien lama membaca "pesan"; isinya tidak boleh ikut berubah."""
    r = buat_sesi(client, "Budi Santoso", "L").json()
    assert r["pesan"] == r["data"]["pembuka"][0]


def test_gelembung_kedua_mengikuti_pengaturan_admin(client):
    """Panitia mengganti identitas di admin, gelembung kedua ikut."""
    from faq.models import PengaturanSapaan

    p = PengaturanSapaan.ambil()
    p.nama_bot = "SI PANDU"
    p.peran_bot = "Asisten PMB"
    p.save()

    d = buat_sesi(client, "Budi Santoso", "L").json()["data"]
    assert "SI PANDU" in d["pembuka"][1]
    assert "Asisten PMB" in d["pembuka"][1]


def test_gelembung_kedua_selalu_ada_selama_identitas_terisi(client):
    """Perkenalan dikosongkan tapi nama bot tetap: gelembung kedua bertahan.

    pesan_identitas selalu menghasilkan minimal "Halo! Saya <nama>.", jadi
    yang hilang hanya paragraf lanjutannya.
    """
    from faq.models import PengaturanSapaan

    p = PengaturanSapaan.ambil()
    p.perkenalan = ""
    p.save()

    d = buat_sesi(client, "Budi Santoso", "L").json()["data"]
    assert len(d["pembuka"]) == 2
    assert d["pembuka"][1] == "Halo! Saya SOBAT KITE, " \
        "Asisten Virtual PMB Universitas Bangka Belitung."


def test_riwayat_mengirim_gelembung_yang_sama(client):
    """Sesi lama dibuka ulang: urutan pembuka identik dengan /session."""
    sesi = buat_sesi(client, "Budi Santoso", "L").json()["data"]
    r = client.get(f"{URL_RIWAYAT}?session_id={sesi['session_id']}")
    assert r.json()["data"]["pembuka"] == sesi["pembuka"]
