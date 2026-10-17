"""Pagar arsitektur: retrieval/ tidak boleh mengenal Django, faq/, atau api/.

Bagian 5 dokumen rencana menyebut ini satu-satunya cara memastikan logika
retrieval benar-benar teruji. Tanpa tes ini, satu `from django.conf import
settings` yang tidak sengaja akan menyelinap masuk dan tidak ada yang tahu
sampai retrieval/ mustahil diuji sendirian.
"""

import ast
import pathlib

import pytest

RETRIEVAL = pathlib.Path(__file__).resolve().parent.parent / "retrieval"

# apps.py memang HARUS mengimpor Django — itu titik sambung ke framework.
DIKECUALIKAN = {"apps.py"}

TERLARANG = ("django", "faq", "api", "percakapan")


def modul_retrieval():
    return [p for p in RETRIEVAL.glob("*.py") if p.name not in DIKECUALIKAN]


def impor_dari(path: pathlib.Path) -> list[str]:
    pohon = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    keluar = []
    for simpul in ast.walk(pohon):
        if isinstance(simpul, ast.Import):
            keluar += [a.name for a in simpul.names]
        elif isinstance(simpul, ast.ImportFrom):
            # level > 0 = impor relatif (from .text import ...) — selalu boleh
            if simpul.level == 0 and simpul.module:
                keluar.append(simpul.module)
    return keluar


@pytest.mark.parametrize("path", modul_retrieval(), ids=lambda p: p.name)
def test_tidak_mengimpor_django_atau_app_lain(path):
    for nama in impor_dari(path):
        akar = nama.split(".")[0]
        assert akar not in TERLARANG, (
            f"{path.name} mengimpor {nama!r}. retrieval/ harus bisa diuji "
            f"tanpa Django dan tanpa basis data — pindahkan ketergantungan ini "
            f"ke pemanggil (faq/ atau api/)."
        )


def test_ada_modul_yang_diperiksa():
    """Menangkap kasus glob gagal dan tes lolos secara semu."""
    nama = {p.name for p in modul_retrieval()}
    assert {"text.py", "engine.py", "tiers.py", "indexer.py"} <= nama


def test_apps_py_sengaja_dikecualikan():
    assert (RETRIEVAL / "apps.py").exists()
    assert "django" in " ".join(impor_dari(RETRIEVAL / "apps.py"))
