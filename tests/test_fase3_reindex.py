"""Tes Fase 3 — reindex, regression gate, rollback, deteksi versi antar-worker.

Memakai ModelTiruan agar tidak memuat model 600 MB; yang diuji di sini adalah
alur reindex/rollback, bukan kualitas retrieval.
"""

import numpy as np
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse

from faq import actions, services
from faq.models import Faq, FaqVariasi, IndexVersion
from retrieval.engine import Engine
from tests.test_engine import ModelTiruan

pytestmark = pytest.mark.django_db


@pytest.fixture
def kb():
    a = Faq.objects.create(pertanyaan="apa itu universitas bangka belitung",
                           jawaban="PTN di Babel.")
    b = Faq.objects.create(pertanyaan="berapa uang kuliah tunggal",
                           jawaban="Bervariasi.")
    FaqVariasi.objects.create(faq=a, teks="ubb itu kampus apa")
    return {"a": a, "b": b}


@pytest.fixture
def engine_tiruan(monkeypatch):
    eng = Engine(ModelTiruan(), None, tau_high=0.72, tau_low=0.60)
    monkeypatch.setattr(services, "muat_engine", lambda: eng)
    return eng


@pytest.fixture
def klien_operator():
    from django.core.management import call_command
    call_command("siapkan_peran")
    u = User.objects.create_user("op3", password="x", is_staff=True)
    u.groups.add(Group.objects.get(name="Operator"))
    c = Client()
    c.force_login(u)
    return c


# --- pengumpulan entri ---------------------------------------------------

def test_variasi_ikut_terindeks(kb):
    entri, peta = actions.kumpulkan_entri()
    assert len(entri) == 3          # 2 pertanyaan + 1 variasi
    assert len(peta) == 2           # peta hanya pertanyaan kanonik


def test_faq_nonaktif_dikeluarkan(kb):
    kb["b"].aktif = False
    kb["b"].save()
    entri, _ = actions.kumpulkan_entri()
    assert all(e["faq_id"] != kb["b"].id for e in entri)


def test_butuh_verifikasi_tetap_masuk_index(kb):
    """Entri belum terverifikasi TETAP di-index agar niat camaba dikenali."""
    kb["a"].butuh_verifikasi = True
    kb["a"].save()
    entri, _ = actions.kumpulkan_entri()
    assert any(e["faq_id"] == kb["a"].id for e in entri)


# --- reindex -------------------------------------------------------------

def test_reindex_membuat_versi_baru(kb, engine_tiruan):
    st = actions.jalankan_reindex(paksa=True, pengguna="uji")
    assert st.berhasil is True
    iv = IndexVersion.objects.get(aktif=True)
    assert iv.versi == 1
    assert iv.jumlah_vektor == 3
    assert iv.jumlah_answer == 2


def test_reindex_menaikkan_nomor_versi(kb, engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    actions.jalankan_reindex(paksa=True)
    assert list(IndexVersion.objects.order_by("versi")
                .values_list("versi", flat=True)) == [1, 2]


def test_hanya_satu_index_aktif(kb, engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    actions.jalankan_reindex(paksa=True)
    assert IndexVersion.objects.filter(aktif=True).count() == 1
    assert IndexVersion.objects.get(aktif=True).versi == 2


def test_reindex_tanpa_faq_ditolak(engine_tiruan):
    with pytest.raises(RuntimeError, match="Tidak ada FAQ aktif"):
        actions.jalankan_reindex(paksa=True)


def test_reindex_tanpa_model_ditolak(kb, monkeypatch):
    monkeypatch.setattr(services, "muat_engine", lambda: None)
    with pytest.raises(RuntimeError, match="Model tidak tersedia"):
        actions.jalankan_reindex(paksa=True)


def test_faq_baru_terjawab_setelah_reindex(kb, engine_tiruan):
    """Definition of done Fase 3, tanpa restart proses."""
    actions.jalankan_reindex(paksa=True)
    baru = Faq.objects.create(
        pertanyaan="apakah ada layanan konseling mahasiswa",
        jawaban="Ya, tersedia.")

    eng = services.engine_siap()
    sebelum = eng.cari("apakah ada layanan konseling mahasiswa", top_k=1)
    assert sebelum[0][0] != baru.id      # belum terjangkau

    actions.jalankan_reindex(paksa=True)
    eng = services.engine_siap()
    sesudah = eng.cari("apakah ada layanan konseling mahasiswa", top_k=1)
    assert sesudah[0][0] == baru.id      # sekarang terjawab


# --- regression gate -----------------------------------------------------

def test_gate_menolak_dan_tidak_menulis_apa_pun(kb, engine_tiruan, monkeypatch,
                                                tmp_path):
    """Gate gagal -> index TIDAK dipasang, versi lama tetap melayani."""
    import json

    from django.conf import settings

    hard = tmp_path / "hard_eval.json"
    hard.write_text(json.dumps({
        "apa itu universitas bangka belitung": ["berapa uang kuliah tunggal"],
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)

    st = actions.jalankan_reindex(paksa=False)
    assert st.berhasil is False
    assert "DITOLAK" in st.pesan
    assert IndexVersion.objects.count() == 0     # nol baris ditulis


def test_gate_bisa_dipaksa(kb, engine_tiruan, monkeypatch, tmp_path):
    import json

    from django.conf import settings

    hard = tmp_path / "hard_eval.json"
    hard.write_text(json.dumps({
        "apa itu universitas bangka belitung": ["berapa uang kuliah tunggal"],
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)

    st = actions.jalankan_reindex(paksa=True)
    assert st.berhasil is True
    assert "DIPAKSA" in IndexVersion.objects.get(aktif=True).catatan


def test_tanpa_hard_eval_gate_dilewati(kb, engine_tiruan, monkeypatch, tmp_path):
    from django.conf import settings
    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)   # kosong
    st = actions.jalankan_reindex(paksa=False)
    assert st.berhasil is True
    assert st.acc_at_1 is None


# --- rollback ------------------------------------------------------------

def test_rollback_mengaktifkan_versi_lama(kb, engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    actions.jalankan_reindex(paksa=True)
    assert IndexVersion.objects.get(aktif=True).versi == 2

    actions.rollback(1, pengguna="uji")
    assert IndexVersion.objects.get(aktif=True).versi == 1
    assert IndexVersion.objects.filter(aktif=True).count() == 1


def test_rollback_mencatat_jejak(kb, engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    actions.jalankan_reindex(paksa=True)
    iv = actions.rollback(1, pengguna="operator1")
    assert "Rollback" in iv.catatan
    assert "operator1" in iv.catatan


def test_rollback_versi_tak_ada(kb, engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    with pytest.raises(IndexVersion.DoesNotExist):
        actions.rollback(99)


def test_rollback_langsung_terasa_di_engine(kb, engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    baru = Faq.objects.create(pertanyaan="apakah ada layanan konseling",
                              jawaban="Ya.")
    actions.jalankan_reindex(paksa=True)

    eng = services.engine_siap()
    assert eng.cari("apakah ada layanan konseling", top_k=1)[0][0] == baru.id

    actions.rollback(1)
    eng = services.engine_siap()
    assert eng.snapshot.versi == 1
    assert eng.cari("apakah ada layanan konseling", top_k=1)[0][0] != baru.id


# --- deteksi versi antar-worker (Bagian 9.3) ----------------------------

def test_sinkronkan_versi_memuat_ulang(kb, engine_tiruan):
    """Reindex dari proses admin harus menyusul ke worker API."""
    actions.jalankan_reindex(paksa=True)
    eng = services.engine_siap()
    assert eng.snapshot.versi == 1

    # Simulasi: proses LAIN membuat v2 dan mengaktifkannya.
    actions.jalankan_reindex(paksa=True)
    eng._snapshot = eng.snapshot.__class__(
        1, eng.snapshot.vektor, eng.snapshot.pemilik, eng.snapshot.dim)
    assert eng.snapshot.versi == 1          # worker ini masih tertinggal

    assert services.sinkronkan_versi(eng) == 2
    assert eng.snapshot.versi == 2


def test_sinkronkan_versi_tidak_memuat_ulang_bila_sama(kb, engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    eng = services.engine_siap()
    snap_lama = eng.snapshot
    assert services.sinkronkan_versi(eng) == 1
    assert eng.snapshot is snap_lama        # objek sama, tidak dibangun ulang


def test_sinkronkan_versi_aman_saat_engine_none():
    assert services.sinkronkan_versi(None) is None


# --- halaman admin -------------------------------------------------------

def test_halaman_index_menampilkan_tombol(klien_operator, kb, engine_tiruan):
    r = klien_operator.get(reverse("admin:faq_indexversion_changelist"))
    assert r.status_code == 200
    assert "Bangun Ulang Index" in r.content.decode()


def test_status_json(klien_operator):
    r = klien_operator.get(reverse("admin:faq_indexversion_status"))
    assert r.status_code == 200
    assert "berjalan" in r.json()


def test_tombol_rollback_muncul_untuk_versi_nonaktif(klien_operator, kb,
                                                     engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    actions.jalankan_reindex(paksa=True)
    isi = klien_operator.get(
        reverse("admin:faq_indexversion_changelist")).content.decode()
    assert "Rollback" in isi
    assert "sedang dipakai" in isi          # versi aktif tidak dapat tombol


def test_rollback_lewat_http(klien_operator, kb, engine_tiruan):
    actions.jalankan_reindex(paksa=True)
    actions.jalankan_reindex(paksa=True)
    r = klien_operator.post(
        reverse("admin:faq_indexversion_rollback", args=[1]), follow=True)
    assert r.status_code == 200
    assert IndexVersion.objects.get(aktif=True).versi == 1


def test_reindex_lewat_http(klien_operator, kb, engine_tiruan):
    r = klien_operator.post(
        reverse("admin:faq_indexversion_reindex"), {"paksa": "1"}, follow=True)
    assert r.status_code == 200


def test_get_tidak_memicu_reindex(klien_operator, kb, engine_tiruan):
    """Aksi yang mengubah keadaan tidak boleh terpicu oleh GET."""
    klien_operator.get(reverse("admin:faq_indexversion_reindex"))
    assert IndexVersion.objects.count() == 0


# --- pembatasan peran ----------------------------------------------------

@pytest.mark.parametrize("grup", ["Editor Konten", "Verifikator"])
def test_non_operator_tidak_bisa_reindex(grup, kb, engine_tiruan):
    from django.core.management import call_command
    call_command("siapkan_peran")
    u = User.objects.create_user(f"x_{grup[:5]}", password="x", is_staff=True)
    u.groups.add(Group.objects.get(name=grup))
    c = Client()
    c.force_login(u)

    assert c.post(reverse("admin:faq_indexversion_reindex")).status_code == 403
    assert c.post(reverse("admin:faq_indexversion_rollback",
                          args=[1])).status_code == 403
    assert IndexVersion.objects.count() == 0


# --- tombol "Pasang paksa" -----------------------------------------------

def test_tombol_paksa_ada_di_halaman(klien_operator, kb, engine_tiruan):
    isi = klien_operator.get(
        reverse("admin:faq_indexversion_changelist")).content.decode()
    assert "Pasang paksa" in isi
    assert 'name="paksa" value="1"' in isi


def test_tombol_paksa_memasang_walau_gate_gagal(klien_operator, kb,
                                                engine_tiruan, monkeypatch,
                                                tmp_path):
    """Gate gagal + paksa -> index TETAP dipasang, dan ditandai [DIPAKSA]."""
    import json

    from django.conf import settings

    hard = tmp_path / "hard_eval.json"
    hard.write_text(json.dumps({
        "apa itu universitas bangka belitung": ["berapa uang kuliah tunggal"],
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)

    # Jalur sinkron: thread latar + SQLite saling mengunci di dalam tes.
    # Yang diuji di sini adalah efek paksa=True, bukan mekanisme thread-nya.
    actions.jalankan_reindex(paksa=True, pengguna="operator")

    iv = IndexVersion.objects.filter(aktif=True).first()
    assert iv is not None, "index tidak terpasang padahal dipaksa"
    assert "DIPAKSA" in iv.catatan


def test_tanpa_paksa_gate_tetap_menolak(klien_operator, kb, engine_tiruan,
                                        monkeypatch, tmp_path):
    """Tombol biasa tidak boleh diam-diam melewati gate."""
    import json

    from django.conf import settings

    hard = tmp_path / "hard_eval.json"
    hard.write_text(json.dumps({
        "apa itu universitas bangka belitung": ["berapa uang kuliah tunggal"],
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "ARTIFACTS_DIR", tmp_path)

    st = actions.jalankan_reindex(paksa=False, pengguna="operator")
    assert st.berhasil is False
    assert IndexVersion.objects.count() == 0


def test_non_operator_tidak_bisa_paksa(kb, engine_tiruan):
    from django.core.management import call_command
    call_command("siapkan_peran")
    u = User.objects.create_user("editor_paksa", password="x", is_staff=True)
    u.groups.add(Group.objects.get(name="Editor Konten"))
    c = Client()
    c.force_login(u)

    r = c.post(reverse("admin:faq_indexversion_reindex"), {"paksa": "1"})
    assert r.status_code == 403
    assert IndexVersion.objects.count() == 0
