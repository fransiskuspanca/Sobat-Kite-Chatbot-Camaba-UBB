"""Tes perbaikan admin panel yang diminta setelah Fase 1."""

import re

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse

from faq.models import Faq

pytestmark = pytest.mark.django_db


@pytest.fixture
def klien_admin():
    u = User.objects.create_superuser("op2", "op2@ubb.ac.id", "rahasia")
    c = Client()
    c.force_login(u)
    return c


# --- 1. Logo UBB ---------------------------------------------------------

def test_logo_tersedia_sebagai_static():
    from django.contrib.staticfiles import finders
    assert finders.find("img/Logo_UBB.png") is not None


def test_logo_terpasang_di_settings():
    from django.conf import settings
    unfold = settings.UNFOLD
    assert "SITE_LOGO" in unfold and "SITE_ICON" in unfold


def test_logo_muncul_di_halaman_login():
    r = Client().get("/admin/login/")
    assert r.status_code == 200
    assert "Logo_UBB.png" in r.content.decode()


def test_logo_muncul_di_sidebar(klien_admin):
    r = klien_admin.get(reverse("admin:index"))
    assert "Logo_UBB.png" in r.content.decode()


def test_logo_dirender_sebagai_img_di_login():
    """Template login unfold hanya menampilkan teks — harus ditimpa."""
    isi = Client().get("/admin/login/").content.decode()
    assert '<img src="/static/img/Logo_UBB.png"' in isi


def test_form_login_tetap_utuh_setelah_template_ditimpa():
    """Menimpa template tidak boleh merusak fungsi login."""
    isi = Client().get("/admin/login/").content.decode()
    assert 'name="username"' in isi
    assert 'name="password"' in isi
    assert "csrfmiddlewaretoken" in isi


def test_login_dibungkus_card_ber_shadow():
    """Form login berada di dalam card putih dengan shadow lembut."""
    isi = Client().get("/admin/login/").content.decode()
    m = re.search(r'<div class="(bg-white border[^"]*)"', isi)
    assert m, "card login tidak ditemukan"
    kelas = m.group(1).split()
    for wajib in ["bg-white", "border", "rounded-default", "shadow-sm"]:
        assert wajib in kelas, f"{wajib} hilang dari card"


def test_kelas_card_benar_benar_ada_di_bundle_css():
    """Tailwind unfold sudah dikompilasi — kelas di luar bundle tidak berefek.

    Menangkap kasus memakai kelas Tailwind yang wajar (mis. p-8, rounded-xl)
    tetapi tidak ikut ter-build, sehingga tampilan diam-diam tidak berubah.
    """
    import pathlib

    import unfold

    css_path = (pathlib.Path(unfold.__file__).parent
                / "static" / "unfold" / "css" / "styles.css")
    css = css_path.read_text(encoding="utf-8")

    isi = Client().get("/admin/login/").content.decode()
    kelas = re.search(r'<div class="(bg-white border[^"]*)"', isi).group(1).split()

    for k in kelas:
        selektor = "." + k.replace(":", r"\:")
        assert re.search(re.escape(selektor) + r"[\{,\s:]", css), (
            f"kelas {k!r} tidak ada di bundle CSS unfold — tidak akan berefek")


def test_login_masih_berfungsi():
    User.objects.create_superuser("uji_login", "u@ubb.ac.id", "SandiKuat!2026")
    c = Client()
    r = c.post("/admin/login/",
               {"username": "uji_login", "password": "SandiKuat!2026",
                "next": "/admin/"}, follow=True)
    assert r.request["PATH_INFO"] == "/admin/"
    assert r.status_code == 200


# --- 2. Tombol edit di daftar FAQ ---------------------------------------

def test_tombol_lengkapi_untuk_yang_menunggu_unit(klien_admin):
    Faq.objects.create(pertanyaan="Berapa luas kampus?",
                       jawaban="Perlu wawancara.", butuh_verifikasi=True)
    r = klien_admin.get(reverse("admin:faq_faq_changelist"))
    assert "✎ Lengkapi" in r.content.decode()


def test_tombol_edit_untuk_yang_sudah_final(klien_admin):
    Faq.objects.create(pertanyaan="Apa itu UBB?", jawaban="PTN di Babel.",
                       butuh_verifikasi=False)
    r = klien_admin.get(reverse("admin:faq_faq_changelist"))
    assert "✎ Edit" in r.content.decode()


def test_tombol_menaut_ke_halaman_ubah_yang_benar(klien_admin):
    f = Faq.objects.create(pertanyaan="Uji tautan?", jawaban="Ya.",
                           butuh_verifikasi=True)
    r = klien_admin.get(reverse("admin:faq_faq_changelist"))
    assert reverse("admin:faq_faq_change", args=[f.pk]) in r.content.decode()


# --- 3. Form tambah pengguna terlihat -----------------------------------

def test_halaman_tambah_pengguna_memakai_gaya_unfold(klien_admin):
    """UserAdmin bawaan Django memakai template polos yang mengabaikan unfold."""
    r = klien_admin.get("/admin/auth/user/add/")
    assert r.status_code == 200
    nama_template = [t.name for t in r.templates if t.name]
    assert "admin/auth/user/add_form.html" not in nama_template


def test_form_tambah_pengguna_punya_semua_field(klien_admin):
    isi = klien_admin.get("/admin/auth/user/add/").content.decode()
    for field in ['name="username"', 'name="password1"', 'name="password2"',
                  'name="is_staff"', 'name="groups"']:
        assert field in isi, f"{field} hilang dari form"


def test_pengguna_benar_benar_bisa_dibuat(klien_admin):
    Group.objects.create(name="Editor Konten")
    r = klien_admin.post("/admin/auth/user/add/", {
        "username": "staf_baru", "password1": "SandiKuat!2026",
        "password2": "SandiKuat!2026", "first_name": "", "last_name": "",
        "email": "", "is_active": "on", "is_staff": "on",
    }, follow=True)
    assert r.status_code == 200
    assert User.objects.filter(username="staf_baru").exists()


def test_halaman_grup_juga_bergaya_unfold(klien_admin):
    r = klien_admin.get("/admin/auth/group/add/")
    assert r.status_code == 200


# --- 4. Root diarahkan ke panel -----------------------------------------

def test_root_diarahkan_ke_admin():
    r = Client().get("/")
    assert r.status_code == 302
    assert r.url == "/admin/"


def test_root_belum_login_berakhir_di_login():
    r = Client().get("/", follow=True)
    assert r.request["PATH_INFO"] == "/admin/login/"


def test_root_sudah_login_berakhir_di_dashboard(klien_admin):
    r = klien_admin.get("/", follow=True)
    assert r.request["PATH_INFO"] == "/admin/"
    assert r.status_code == 200


# --- 5. Halaman Versi index hanya untuk Operator -------------------------
#
# Halaman ini menyimpan vektor index + skor regression gate, dan satu-satunya
# jalan rollback saat chatbot menjawab ngawur setelah update. Isinya teknis
# dan tidak ada hubungannya dengan pekerjaan mengurasi FAQ, jadi disembunyikan
# dari panitia (Bagian 7.5: reindex & rollback = kewenangan Operator).

def _pengguna_bergrup(nama, grup):
    from django.core.management import call_command
    call_command("siapkan_peran")
    u = User.objects.create_user(nama, password="x", is_staff=True)
    u.groups.add(Group.objects.get(name=grup))
    c = Client()
    c.force_login(u)
    return c


@pytest.mark.parametrize("grup", ["Editor Konten", "Verifikator"])
def test_versi_index_tersembunyi_dari_panitia(grup):
    c = _pengguna_bergrup(f"uji_{grup[:5].lower().strip()}", grup)
    assert c.get("/admin/faq/indexversion/").status_code == 403
    assert "Versi index" not in c.get("/admin/").content.decode()


def test_versi_index_terbuka_untuk_operator():
    c = _pengguna_bergrup("uji_operator", "Operator")
    assert c.get("/admin/faq/indexversion/").status_code == 200
    assert "Versi index" in c.get("/admin/").content.decode()


def test_versi_index_terbuka_untuk_superuser(klien_admin):
    assert klien_admin.get("/admin/faq/indexversion/").status_code == 200


@pytest.mark.parametrize("grup", ["Editor Konten", "Verifikator", "Operator"])
def test_pembatasan_tidak_mengganggu_pekerjaan_panitia(grup):
    """Menyembunyikan Versi index tidak boleh memblokir akses ke FAQ."""
    c = _pengguna_bergrup(f"uji2_{grup[:5].lower().strip()}", grup)
    assert c.get("/admin/faq/faq/").status_code == 200


# --- 6. Teks nama institusi di header sidebar ---------------------------

def test_header_sidebar_menampilkan_nama_institusi(klien_admin):
    """Template unfold hanya menampilkan logo tanpa teks — ditimpa."""
    isi = klien_admin.get("/admin/").content.decode()
    blok = re.search(
        r'<div class="bg-transparent border border-transparent flex font-semibold.*?</div>\s*</div>',
        isi, re.S)
    assert blok, "blok header sidebar tidak ditemukan"
    assert "Chatbot PMB UBB" in blok.group(0)
    assert "Universitas Bangka Belitung" in blok.group(0)


def test_logo_tetap_ada_di_header_sidebar(klien_admin):
    isi = klien_admin.get("/admin/").content.decode()
    blok = re.search(
        r'<div class="bg-transparent border border-transparent flex font-semibold.*?</div>\s*</div>',
        isi, re.S).group(0)
    assert "Logo_UBB.png" in blok


def test_logo_tidak_lagi_punya_margin_dobel(klien_admin):
    """Wadah sudah gap-3; mr-4 bawaan unfold membuat jarak jadi dobel."""
    isi = klien_admin.get("/admin/").content.decode()
    m = re.search(r'<img src="/static/img/Logo_UBB\.png" class="([^"]*)"', isi)
    assert m, "logo sidebar tidak ditemukan"
    assert "mr-4" not in m.group(1)


def test_kelas_header_sidebar_ada_di_bundle_css(klien_admin):
    """Kelas di luar bundle Tailwind unfold tidak berefek apa pun."""
    import pathlib

    import unfold

    css = (pathlib.Path(unfold.__file__).parent
           / "static" / "unfold" / "css" / "styles.css").read_text(encoding="utf-8")

    isi = klien_admin.get("/admin/").content.decode()
    blok = re.search(
        r'<div class="bg-transparent border border-transparent flex font-semibold.*?</div>\s*</div>',
        isi, re.S).group(0)

    kelas = set()
    for m in re.finditer(r'class="([^"]*)"', blok):
        kelas.update(m.group(1).split())

    for k in kelas:
        if k.startswith(("h-[", "-mx-", "px-", "gap-")):
            continue                      # nilai arbitrer / sudah dipakai unfold
        selektor = "." + k.replace(":", r"\:")
        assert re.search(re.escape(selektor) + r"[\{,\s:]", css), (
            f"kelas {k!r} tidak ada di bundle CSS unfold")
