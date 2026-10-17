"""Tes admin panel Fase 1 — halaman, aksi massal, peran, cek tabrakan."""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.contrib.messages import get_messages
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from faq.models import Faq, FaqVariasi, IndexVersion
from percakapan.models import ChatLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def faq_contoh():
    return Faq.objects.create(
        pertanyaan="Apa itu UBB?", jawaban="PTN di Bangka Belitung.",
        kategori="A. Umum", sumber_label="Profil UBB")


@pytest.fixture
def faq_belum_verif():
    return Faq.objects.create(
        pertanyaan="Berapa luas kampus?",
        jawaban="Perlu wawancara. (Tidak ditemukan angka resmi.)",
        kategori="A. Umum", butuh_verifikasi=True)


@pytest.fixture
def klien_admin():
    u = User.objects.create_superuser("op", "op@ubb.ac.id", "rahasia")
    c = Client()
    c.force_login(u)
    return c


# --- halaman bisa dibuka -------------------------------------------------

@pytest.mark.parametrize("nama_url", [
    "admin:index",
    "admin:faq_faq_changelist",
    "admin:faq_faq_add",
    "admin:faq_faqvariasi_changelist",
    "admin:faq_indexversion_changelist",
    "admin:percakapan_chatlog_changelist",
    "admin:antrean_konten",
])
def test_halaman_admin_terbuka(klien_admin, nama_url):
    assert klien_admin.get(reverse(nama_url)).status_code == 200


def test_halaman_ubah_faq(klien_admin, faq_contoh):
    r = klien_admin.get(reverse("admin:faq_faq_change", args=[faq_contoh.pk]))
    assert r.status_code == 200


def test_filter_butuh_verifikasi(klien_admin, faq_contoh, faq_belum_verif):
    """70 dari 260 jawaban belum final — filter ini mengubahnya jadi daftar kerja."""
    url = reverse("admin:faq_faq_changelist") + "?butuh_verifikasi__exact=1"
    r = klien_admin.get(url)
    assert r.status_code == 200
    isi = r.content.decode()
    assert "Berapa luas kampus?" in isi
    assert "Apa itu UBB?" not in isi


def test_pencarian_menjangkau_variasi(klien_admin, faq_contoh):
    """search_fields mencakup variasi__teks."""
    FaqVariasi.objects.create(faq=faq_contoh, teks="kampus ubb itu apa")
    r = klien_admin.get(reverse("admin:faq_faq_changelist") + "?q=kampus+ubb")
    assert r.status_code == 200
    assert "Apa itu UBB?" in r.content.decode()


# --- prefill dari antrean konten ----------------------------------------

def test_tombol_buat_faq_mengisi_pertanyaan(klien_admin):
    """Menutup lingkaran: camaba bertanya -> admin klik -> pertanyaan terisi."""
    url = reverse("admin:faq_faq_add") + "?pertanyaan=berapa+ukt+teknik+mesin"
    r = klien_admin.get(url)
    assert r.status_code == 200
    assert "berapa ukt teknik mesin" in r.content.decode()


def test_antrean_menampilkan_pertanyaan_gagal(klien_admin):
    for i in range(3):
        ChatLog.objects.create(log_id=f"L{i}", query="berapa ukt teknik mesin",
                               tipe="fallback", skor=0.4)
    ChatLog.objects.create(log_id="OK", query="apa itu ubb",
                           tipe="jawaban", skor=0.95)

    r = klien_admin.get(reverse("admin:antrean_konten"))
    isi = r.content.decode()
    assert "berapa ukt teknik mesin" in isi
    # Yang BERHASIL dijawab tidak boleh masuk antrean
    assert "apa itu ubb" not in isi


def test_antrean_kosong_tidak_error(klien_admin):
    r = klien_admin.get(reverse("admin:antrean_konten"))
    assert r.status_code == 200
    assert "Antrean kosong" in r.content.decode()


# --- aksi massal ---------------------------------------------------------

def test_aksi_tandai_terverifikasi(klien_admin, faq_belum_verif):
    """Panitia menyetujui 20 jawaban sekaligus, bukan satu per satu."""
    klien_admin.post(reverse("admin:faq_faq_changelist"), {
        "action": "tandai_terverifikasi",
        "_selected_action": [str(faq_belum_verif.pk)],
    }, follow=True)

    faq_belum_verif.refresh_from_db()
    assert faq_belum_verif.butuh_verifikasi is False
    assert faq_belum_verif.terakhir_diverifikasi == date.today()


def test_aksi_tandai_butuh_verifikasi(klien_admin, faq_contoh):
    klien_admin.post(reverse("admin:faq_faq_changelist"), {
        "action": "tandai_butuh_verifikasi",
        "_selected_action": [str(faq_contoh.pk)],
    }, follow=True)
    faq_contoh.refresh_from_db()
    assert faq_contoh.butuh_verifikasi is True


def test_aksi_nonaktifkan(klien_admin, faq_contoh):
    klien_admin.post(reverse("admin:faq_faq_changelist"), {
        "action": "nonaktifkan", "_selected_action": [str(faq_contoh.pk)],
    }, follow=True)
    faq_contoh.refresh_from_db()
    assert faq_contoh.aktif is False


# --- peran pengguna (Bagian 7.5) ----------------------------------------

def test_siapkan_peran_membuat_tiga_grup():
    call_command("siapkan_peran")
    assert set(Group.objects.values_list("name", flat=True)) == {
        "Editor Konten", "Verifikator", "Operator"}


def test_editor_tidak_bisa_verifikasi():
    """Menyetujui jawaban adalah kewenangan kepala unit, bukan editor."""
    call_command("siapkan_peran")
    u = User.objects.create_user("editor", password="x", is_staff=True)
    u.groups.add(Group.objects.get(name="Editor Konten"))
    assert u.has_perm("faq.change_faq")
    assert not u.has_perm("faq.dapat_verifikasi")


def test_verifikator_bisa_verifikasi():
    call_command("siapkan_peran")
    u = User.objects.create_user("kepala", password="x", is_staff=True)
    u.groups.add(Group.objects.get(name="Verifikator"))
    assert u.has_perm("faq.dapat_verifikasi")
    assert not u.has_perm("faq.dapat_reindex")


def test_operator_bisa_reindex():
    call_command("siapkan_peran")
    u = User.objects.create_user("operator", password="x", is_staff=True)
    u.groups.add(Group.objects.get(name="Operator"))
    assert u.has_perm("faq.dapat_reindex")


def test_aksi_verifikasi_tersembunyi_dari_editor(faq_belum_verif):
    """Aksi massal verifikasi tidak boleh muncul untuk Editor Konten."""
    call_command("siapkan_peran")
    u = User.objects.create_user("editor2", password="x", is_staff=True)
    u.groups.add(Group.objects.get(name="Editor Konten"))
    c = Client()
    c.force_login(u)

    r = c.get(reverse("admin:faq_faq_changelist"))
    isi = r.content.decode()
    assert "tandai_terverifikasi" not in isi


# --- pratinjau & kolom ---------------------------------------------------

def test_pratinjau_menyembunyikan_jawaban_belum_terverifikasi(
        klien_admin, faq_belum_verif):
    """Prinsip #4 harus terlihat di panel, bukan cuma di runtime."""
    r = klien_admin.get(
        reverse("admin:faq_faq_change", args=[faq_belum_verif.pk]))
    isi = r.content.decode()
    assert "belum punya data resmi yang terverifikasi" in isi
    assert "menunggu persetujuan unit" in isi.lower()


def test_pratinjau_menampilkan_sumber(klien_admin, faq_contoh):
    r = klien_admin.get(reverse("admin:faq_faq_change", args=[faq_contoh.pk]))
    assert "📎 Sumber: Profil UBB" in r.content.decode()


def test_kolom_kesegaran_menandai_kedaluwarsa(klien_admin, faq_contoh):
    """Data PMB kedaluwarsa tiap tahun."""
    faq_contoh.terakhir_diverifikasi = date.today() - timedelta(days=400)
    faq_contoh.save()
    r = klien_admin.get(reverse("admin:faq_faq_changelist"))
    assert "lebih 12 bln" in r.content.decode()


def test_kolom_kesegaran_tidak_menandai_yang_masih_baru(klien_admin, faq_contoh):
    faq_contoh.terakhir_diverifikasi = date.today() - timedelta(days=30)
    faq_contoh.save()
    r = klien_admin.get(reverse("admin:faq_faq_changelist"))
    assert "lebih 12 bln" not in r.content.decode()


# --- cek tabrakan (Bagian 7.2) ------------------------------------------

def test_cek_tabrakan_memperingatkan_bukan_memblokir(klien_admin, faq_contoh,
                                                     monkeypatch):
    """Peringatan, BUKAN blokir. Admin mungkin punya alasan sah."""
    import faq.admin as modul

    monkeypatch.setattr(modul.services, "cari_tabrakan",
                        lambda *a, **kw: [{"faq": faq_contoh, "skor": 0.97}])

    r = klien_admin.post(reverse("admin:faq_faq_add"), {
        "pertanyaan": "UBB itu apa?", "jawaban": "Duplikat.",
        "kategori": "A. Umum", "sub_kategori": "",
        "sumber_label": "", "sumber_url": "",
        "terakhir_diverifikasi": "", "berlaku_sampai": "", "aktif": "on",
        "variasi-TOTAL_FORMS": "0", "variasi-INITIAL_FORMS": "0",
        "variasi-MIN_NUM_FORMS": "0", "variasi-MAX_NUM_FORMS": "1000",
    }, follow=True)

    pesan = " ".join(str(m.message) for m in get_messages(r.wsgi_request))
    assert "Sangat mirip" in pesan
    assert "0.97" in pesan
    # TETAP tersimpan
    assert Faq.objects.filter(pertanyaan="UBB itu apa?").exists()


def test_cek_tabrakan_tidak_menjatuhkan_admin_saat_engine_mati(
        klien_admin, monkeypatch):
    """Prinsip #6 — engine mati tidak boleh menghalangi panitia bekerja."""
    import faq.services as svc

    monkeypatch.setattr(svc, "engine_siap",
                        lambda: (_ for _ in ()).throw(RuntimeError("mati")))
    assert svc.cari_tabrakan("apa pun") == []


def test_cek_tabrakan_tanpa_index_kosong(monkeypatch):
    import faq.services as svc
    monkeypatch.setattr(svc, "engine_siap", lambda: None)
    assert svc.cari_tabrakan("apa pun") == []


# --- IndexVersion read-only ---------------------------------------------

def test_index_version_tidak_bisa_ditambah_manual(klien_admin):
    r = klien_admin.get(reverse("admin:faq_indexversion_add"))
    assert r.status_code in (302, 403)


def test_index_version_menampilkan_akurasi(klien_admin):
    IndexVersion.objects.create(versi=1, vektor=b"", pemilik=[1], dim=384,
                                jumlah_vektor=1, jumlah_answer=1,
                                acc_at_1=0.891, aktif=True)
    r = klien_admin.get(reverse("admin:faq_indexversion_changelist"))
    isi = r.content.decode()
    assert "0.891" in isi
    assert "AKTIF" in isi


def test_chatlog_read_only(klien_admin):
    ChatLog.objects.create(log_id="X1", query="apa itu ubb",
                           tipe="jawaban", skor=0.95)
    r = klien_admin.get(reverse("admin:percakapan_chatlog_add"))
    assert r.status_code in (302, 403)


# --- menu Calon Camaba ---------------------------------------------------

def test_daftar_calon_camaba_menampilkan_kolom_yang_diminta(klien_admin):
    """Nomor, Nama Lengkap, Jenis Kelamin, Email, Waktu."""
    from percakapan.models import Sesi

    Sesi.objects.create(nama_lengkap="Budi Santoso", jenis_kelamin="L",
                        email="budi@example.com")
    Sesi.objects.create(nama_lengkap="Siti Aminah", jenis_kelamin="P")

    r = klien_admin.get(reverse("admin:percakapan_sesi_changelist"))
    assert r.status_code == 200
    isi = r.content.decode()

    for judul in ("Nomor", "Nama lengkap", "Jenis kelamin", "Email", "Waktu"):
        assert judul in isi

    assert "Budi Santoso" in isi
    assert "budi@example.com" in isi
    assert "Siti Aminah" in isi
    # Email kosong tampil sebagai strip, bukan sel kosong yang membingungkan.
    assert "—" in isi


def test_nomor_calon_camaba_lanjut_di_halaman_kedua(klien_admin):
    """Halaman 2 tidak boleh mengulang dari 1 — nomor mengikuti urutan daftar."""
    from percakapan.admin import SesiAdmin
    from percakapan.models import Sesi

    for i in range(SesiAdmin.list_per_page + 3):
        Sesi.objects.create(nama_lengkap=f"Camaba {i:03d}", jenis_kelamin="L")

    url = reverse("admin:percakapan_sesi_changelist")

    # Halaman 1 mulai dari nomor 1 (p 1-indexed sejak Django 4.1).
    r1 = klien_admin.get(url)
    assert r1.status_code == 200
    cl1 = r1.context["cl"]
    assert cl1.model_admin.nomor(cl1.result_list[0]) == 1

    # Halaman 2 melanjutkan, bukan mengulang dari 1.
    r2 = klien_admin.get(url + "?p=2")
    assert r2.status_code == 200
    cl2 = r2.context["cl"]
    assert cl2.model_admin.nomor(cl2.result_list[0]) == SesiAdmin.list_per_page + 1


def test_calon_camaba_tidak_bisa_ditambah_atau_disunting(klien_admin):
    """Read-only: identitas dicatat sistem, bukan diketik panitia."""
    r = klien_admin.get(reverse("admin:percakapan_sesi_add"))
    assert r.status_code in (302, 403)


# --- pengaturan kata pengantar pembuka -----------------------------------

def test_pengaturan_sapaan_selalu_satu_baris():
    """Singleton: create berkali-kali tetap menyisakan satu baris."""
    from faq.models import PengaturanSapaan

    PengaturanSapaan.objects.create(salam="Halo")
    PengaturanSapaan.objects.create(salam="Hai")
    PengaturanSapaan.objects.create(salam="Selamat datang")

    assert PengaturanSapaan.objects.count() == 1
    assert PengaturanSapaan.ambil().salam == "Selamat datang"


def test_pengaturan_sapaan_tidak_bisa_dihapus():
    """Tanpa baris ini sambutan camaba jadi kosong."""
    from faq.models import PengaturanSapaan

    p = PengaturanSapaan.ambil()
    p.delete()
    assert PengaturanSapaan.objects.count() == 1


def test_menu_pengaturan_membelokkan_ke_form_tunggal(klien_admin):
    """Changelist tidak berguna untuk satu baris — langsung ke form."""
    from faq.models import PengaturanSapaan

    r = klien_admin.get(reverse("admin:faq_pengaturansapaan_changelist"))
    assert r.status_code == 302
    obj = PengaturanSapaan.ambil()
    assert r["Location"] == reverse("admin:faq_pengaturansapaan_change",
                                    args=[obj.pk])


def test_form_pengaturan_menampilkan_pratinjau(klien_admin):
    from faq.models import PengaturanSapaan

    obj = PengaturanSapaan.ambil()
    r = klien_admin.get(reverse("admin:faq_pengaturansapaan_change",
                                args=[obj.pk]))
    assert r.status_code == 200
    isi = r.content.decode()
    assert "Budi Santoso" in isi and "Siti Aminah" in isi


def test_simpan_pengaturan_mengubah_sambutan(klien_admin):
    from faq.models import PengaturanSapaan

    obj = PengaturanSapaan.ambil()
    r = klien_admin.post(
        reverse("admin:faq_pengaturansapaan_change", args=[obj.pk]),
        {"salam": "Assalamualaikum", "kalimat": "silakan bertanya.",
         "pakai_sapaan_gender": "on",
         "nama_bot": "SOBAT KITE",
         "peran_bot": "Asisten Virtual PMB Universitas Bangka Belitung",
         "perkenalan": "Ada yang ingin Anda tanyakan?"})
    assert r.status_code == 302

    obj.refresh_from_db()
    assert obj.salam == "Assalamualaikum"
    assert obj.untuk("Budi", "Bang") == "Assalamualaikum Bang Budi, silakan bertanya."


def test_pengaturan_sapaan_tak_menyediakan_tombol_tambah(klien_admin):
    r = klien_admin.get(reverse("admin:faq_pengaturansapaan_add"))
    assert r.status_code in (302, 403)


def test_form_menolak_template_tanpa_placeholder():
    """Tanpa {kunci}, jawaban tidak menyebut pertanyaan camaba."""
    from faq.admin import PengaturanSapaanForm
    from faq.models import PengaturanSapaan

    obj = PengaturanSapaan.ambil()
    f = PengaturanSapaanForm(
        instance=obj,
        data={"salam": "Halo", "kalimat": "silakan bertanya.",
              "nama_bot": "SOBAT KITE", "peran_bot": "Asisten",
              "perkenalan": "Halo.",
              "fallback_template": "Maaf, di luar cakupan saya.",
              "fallback_tanpa_kunci": "Maaf, belum paham."})
    assert not f.is_valid()
    assert "fallback_template" in f.errors


def test_form_menolak_placeholder_asing():
    from faq.admin import PengaturanSapaanForm
    from faq.models import PengaturanSapaan

    obj = PengaturanSapaan.ambil()
    f = PengaturanSapaanForm(
        instance=obj,
        data={"salam": "Halo", "kalimat": "silakan bertanya.",
              "nama_bot": "SOBAT KITE", "peran_bot": "Asisten",
              "perkenalan": "Halo.",
              "fallback_template": "Maaf tentang {kunci} dan {kata}.",
              "fallback_tanpa_kunci": "Maaf, belum paham."})
    assert not f.is_valid()
    assert "fallback_template" in f.errors


def test_form_menolak_kunci_di_kolom_cadangan():
    """Kolom cadangan dipakai justru saat kunci kosong."""
    from faq.admin import PengaturanSapaanForm
    from faq.models import PengaturanSapaan

    obj = PengaturanSapaan.ambil()
    f = PengaturanSapaanForm(
        instance=obj,
        data={"salam": "Halo", "kalimat": "silakan bertanya.",
              "nama_bot": "SOBAT KITE", "peran_bot": "Asisten",
              "perkenalan": "Halo.",
              "fallback_template": "Maaf tentang {kunci}.",
              "fallback_tanpa_kunci": "Maaf, {kunci} belum paham."})
    assert not f.is_valid()
    assert "fallback_tanpa_kunci" in f.errors


def test_form_menerima_template_yang_benar():
    from faq.admin import PengaturanSapaanForm
    from faq.models import PengaturanSapaan

    obj = PengaturanSapaan.ambil()
    f = PengaturanSapaanForm(
        instance=obj,
        data={"salam": "Halo", "kalimat": "silakan bertanya.",
              "nama_bot": "SOBAT KITE", "peran_bot": "Asisten",
              "perkenalan": "Halo.",
              "fallback_template": "Maaf tentang {kunci}.",
              "fallback_tanpa_kunci": "Maaf, belum paham."})
    assert f.is_valid(), f.errors
