"""Tes paket data tambahan (faq/sinkron.py + manage.py sinkron_data)."""

import json

import pytest
from django.core.management import call_command

from faq import sinkron
from faq.models import Faq, FaqVariasi

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def artefak(tmp_path, settings):
    settings.ARTIFACTS_DIR = tmp_path / "artifacts"
    return settings.ARTIFACTS_DIR


@pytest.fixture
def kb():
    biaya = Faq.objects.create(pertanyaan="Berapa biaya kuliah?", jawaban="Rp1 juta.")
    FaqVariasi.objects.create(faq=biaya, teks="ukt berapa")
    return biaya


def tulis_paket(folder, **paket):
    folder.mkdir(exist_ok=True)
    nama = f"paket{len(list(folder.glob('paket*.json'))) + 1}.json"
    (folder / nama).write_text(json.dumps(paket), encoding="utf-8")
    daftar = sorted(p.name for p in folder.glob("paket*.json"))
    (folder / "daftar.json").write_text(json.dumps(daftar), encoding="utf-8")
    return nama


def test_variasi_dan_faq_baru_ditambahkan(kb):
    h = sinkron.terapkan_paket({
        "variasi": {"berapa biaya kuliah?": ["biaya kuliah per semester", "ukt berapa"]},
        "faq_baru": [{"pertanyaan": "Ada asrama?", "jawaban": "Ada.",
                      "butuh_verifikasi": False, "variasi": ["asrama ubb ada?"]}],
    })
    assert (h.faq_baru, h.variasi_baru) == (1, 2)
    assert kb.variasi.filter(teks="biaya kuliah per semester", asal="augmentasi").exists()
    asrama = Faq.objects.get(pertanyaan="Ada asrama?")
    assert asrama.butuh_verifikasi is False
    assert list(asrama.variasi.values_list("teks", flat=True)) == ["asrama ubb ada?"]


def test_faq_baru_tanpa_keterangan_menunggu_verifikasi():
    sinkron.terapkan_paket({"faq_baru": [{"pertanyaan": "Ada asrama?", "jawaban": "Ada."}]})
    assert Faq.objects.get().butuh_verifikasi is True


def test_jawaban_yang_ada_tidak_ditimpa(kb):
    h = sinkron.terapkan_paket({"faq_baru": [
        {"pertanyaan": "Berapa biaya kuliah?", "jawaban": "Gratis.",
         "variasi": ["biaya kuliahnya"]}]})
    kb.refresh_from_db()
    assert kb.jawaban == "Rp1 juta."
    assert h.faq_baru == 0 and h.variasi_baru == 1
    assert h.peringatan


def test_teks_milik_faq_lain_dan_hard_eval_dilewati(kb):
    lain = Faq.objects.create(pertanyaan="Kapan daftar?", jawaban="Maret.")
    h = sinkron.terapkan_paket(
        {"variasi": {"Kapan daftar?": ["UKT berapa", "berapa biaya kuliah?",
                                        "kapan pendaftaran dibuka"]}},
        terlarang={"kapan pendaftaran dibuka"})
    assert h.variasi_baru == 0
    assert not lain.variasi.exists()


def test_paket_rusak_tidak_menulis_apa_pun(kb):
    with pytest.raises(AttributeError):
        sinkron.terapkan_paket({"variasi": {"Berapa biaya kuliah?": ["oke"]},
                                "faq_baru": ["bukan objek"]})
    assert FaqVariasi.objects.count() == 1


def test_jalankan_sekali_per_paket(kb, tmp_path):
    folder = tmp_path / "sinkron"
    tulis_paket(folder, variasi={"Berapa biaya kuliah?": ["biaya semester"]})
    assert sinkron.jalankan(str(folder)) == 1
    assert sinkron.jalankan(str(folder)) == 0
    tulis_paket(folder, variasi={"Berapa biaya kuliah?": ["spp berapa"]})
    assert sinkron.jalankan(str(folder)) == 1
    st = sinkron.muat_status()
    assert set(st) == {"paket1.json", "paket2.json"}
    assert all(s["hasil"] == "ok" for s in st.values())


def test_paket_gagal_dicoba_lagi_hanya_bila_berubah(kb, tmp_path):
    folder = tmp_path / "sinkron"
    nama = tulis_paket(folder)
    (folder / nama).write_text("{rusak", encoding="utf-8")
    pesan = []
    assert sinkron.jalankan(str(folder), tulis=pesan.append) == 0
    assert sinkron.muat_status()[nama]["hasil"] == "gagal"
    assert sinkron.jalankan(str(folder), tulis=pesan.append) == 0
    assert len(pesan) == 1
    (folder / nama).write_text(json.dumps({"variasi": {"Berapa biaya kuliah?": ["spp"]}}),
                               encoding="utf-8")
    assert sinkron.jalankan(str(folder)) == 1


class StatusTiruan:
    def __init__(self, berhasil):
        self.berhasil = berhasil
        self.pesan = "Index v2 aktif" if berhasil else "Acc@1 0.700 < 0.85"
        self.acc_at_1 = 0.9 if berhasil else 0.7
        self.versi_baru = 2


def test_perintah_reindex_hanya_bila_ada_perubahan(kb, tmp_path, monkeypatch):
    from faq import actions
    dipanggil = []
    monkeypatch.setattr(actions, "jalankan_reindex",
                        lambda **kw: dipanggil.append(kw) or StatusTiruan(True))
    folder = tmp_path / "sinkron"
    tulis_paket(folder, variasi={"Berapa biaya kuliah?": ["biaya semester"]})
    tulis_paket(folder, variasi={"Berapa biaya kuliah?": ["ukt berapa"]})  # tidak mengubah apa pun
    call_command("sinkron_data", "--sumber", str(folder))
    call_command("sinkron_data", "--sumber", str(folder))
    assert [kw["pengguna"] for kw in dipanggil] == ["sinkron"]
    assert dipanggil[0]["ambang"] == pytest.approx(0.85)
    st = sinkron.muat_status()["paket1.json"]
    assert st["acc_at_1"] == 0.9 and st["variasi_baru"] == 1


def test_paket_yang_menurunkan_akurasi_dibatalkan(kb, tmp_path, monkeypatch):
    from faq import actions
    monkeypatch.setattr(actions, "jalankan_reindex", lambda **kw: StatusTiruan(False))
    folder = tmp_path / "sinkron"
    tulis_paket(folder, variasi={"Berapa biaya kuliah?": ["biaya semester"]},
                faq_baru=[{"pertanyaan": "Ada asrama?", "jawaban": "Ada.",
                           "variasi": ["asrama ubb"]}])
    call_command("sinkron_data", "--sumber", str(folder))
    assert list(Faq.objects.values_list("pertanyaan", flat=True)) == ["Berapa biaya kuliah?"]
    assert FaqVariasi.objects.count() == 1
    assert sinkron.muat_status()["paket1.json"]["hasil"] == "ditolak"


def test_ambang_paket_adalah_akurasi_index_aktif(kb, tmp_path, monkeypatch):
    from faq import actions
    from faq.models import IndexVersion
    IndexVersion.objects.create(versi=1, vektor=b"", pemilik=[], dim=1, jumlah_vektor=0,
                                jumlah_answer=0, acc_at_1=0.9167, aktif=True)
    ambang = []
    monkeypatch.setattr(actions, "jalankan_reindex",
                        lambda **kw: ambang.append(kw["ambang"]) or StatusTiruan(True))
    folder = tmp_path / "sinkron"
    tulis_paket(folder, variasi={"Berapa biaya kuliah?": ["biaya semester"]})
    call_command("sinkron_data", "--sumber", str(folder))
    assert ambang and abs(ambang[0] - 0.9167) < 1e-6


def test_halaman_laporan_simulasi(kb, tmp_path, monkeypatch):
    from django.contrib.auth.models import User
    from django.test import Client
    from django.urls import reverse

    folder = tmp_path / "sinkron"
    tulis_paket(folder, keterangan="Simulasi jalur mandiri",
                variasi={"Berapa biaya kuliah?": ["biaya semester"]})
    sinkron.jalankan(str(folder))
    c = Client()
    c.force_login(User.objects.create_superuser("op", "op@ubb.ac.id", "rahasia"))
    r = c.get(reverse("admin:laporan_simulasi"))
    assert r.status_code == 200
    isi = r.content.decode()
    assert "Simulasi jalur mandiri" in isi and "1 variasi baru" in isi
