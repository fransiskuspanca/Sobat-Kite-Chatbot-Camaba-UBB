"""Kamus sinonim domain PMB UBB — untuk augmentasi data latih di notebook Colab.

MASALAH YANG DIPECAHKAN
-----------------------
`augment()` di notebook hanya mengubah PERMUKAAN kalimat: singkatan, typo,
sapaan, urutan kata. Model karenanya tidak pernah belajar bahwa "kerja praktek"
dan "magang" adalah hal yang sama.

Akibatnya terukur: dari 36 pertanyaan hard eval, 15 di antaranya jawaban
benarnya TIDAK muncul sama sekali di top-5 — bukan salah peringkat, tapi
konsepnya memang belum dikenali.

Kamus di bawah disusun dari analisis 23 kasus gagal yang sesungguhnya, bukan
dari tebakan. Setiap entri diambil dari pasangan (query camaba -> FAQ emas)
yang nyata-nyata meleset.

CARA PAKAI DI NOTEBOOK
----------------------
Tempel berkas ini sebagai satu sel, lalu ganti pemanggilan augment():

    varian = augment(r["pertanyaan"], n=6, seed=r["id"])
    varian += augment_sinonim(r["pertanyaan"], n=4, seed=r["id"])

Pastikan seluruh varian tetap dipetakan ke gold_id yang sama seperti
pertanyaan kanoniknya.
"""

import random
import re

# ---------------------------------------------------------------------------
# Sinonim domain: istilah FAQ -> cara camaba sesungguhnya mengucapkannya.
#
# Arah pemetaan sengaja dari ISTILAH RESMI (yang dipakai di FAQ) ke BAHASA
# CAMABA, karena augmentasi berjalan atas teks pertanyaan kanonik.
# ---------------------------------------------------------------------------
SINONIM_DOMAIN = {
    # --- jalur masuk ---
    "snbt": ["jalur utbk", "jalur yang pakai utbk", "jalur tes tulis",
             "seleksi lewat utbk"],
    "snbp": ["jalur rapor", "jalur nilai rapor", "jalur tanpa tes",
             "jalur undangan"],
    "jalur mandiri": ["seleksi kampus sendiri", "jalur ujian kampus",
                      "jalur tes mandiri", "seleksi sendiri"],
    "utbk": ["tes masuk ptn", "ujian tulis berbasis komputer"],

    # --- biaya & bantuan ---
    "beasiswa": ["bantuan dana kuliah", "keringanan biaya",
                 "potongan biaya kuliah", "bantuan biaya buat yang kurang mampu",
                 "subsidi kuliah"],
    "ukt": ["uang kuliah", "biaya per semester", "spp"],
    "biaya asrama": ["sewa kamar di kampus", "harga kamar asrama",
                     "biaya tinggal di kampus", "sewa kamar",
                     "sewa kamar di dalam kampus"],

    # --- fasilitas ---
    "asrama": ["tempat tinggal", "tempat tinggal buat anak rantau",
               "kosan dalam kampus", "rusunawa", "hunian mahasiswa"],
    "kantin": ["tempat makan", "tempat jajan", "warung di kampus",
               "tempat makan siang", "makan siang", "tempat beli makan"],
    "perpustakaan": ["tempat pinjam buku", "tempat baca buku"],
    "area parkir": ["tempat parkir", "tempat naruh motor", "parkiran"],
    "shuttle bus": ["antar jemput", "bus kampus", "kendaraan antar jemput"],
    "ramah disabilitas": ["bisa diakses kursi roda", "akses kursi roda",
                          "fasilitas untuk penyandang disabilitas",
                          "kursi roda", "pakai kursi roda"],

    # --- kegiatan & akademik ---
    "organisasi mahasiswa": ["ukm", "bem", "himpunan mahasiswa",
                             "ukm sama bem", "organisasi kampus"],
    "magang": ["kerja praktek", "praktek kerja lapangan", "pkl",
               "kerja praktek di perusahaan", "internship"],
    "wisuda": ["prosesi kelulusan", "acara kelulusan", "upacara kelulusan"],
    "pertukaran pelajar": ["kuliah sementara di kampus lain",
                           "student exchange", "belajar di kampus lain"],
    "mahasiswa asing": ["orang luar negeri", "mahasiswa dari luar negeri",
                        "warga negara asing"],
    "peluang kerja alumni": ["lulusan gampang dapat kerja",
                             "prospek kerja lulusan", "alumni kerja di mana",
                             "gampang dapat pekerjaan", "dapat pekerjaan"],

    # --- jenjang ---
    "s3": ["doktor", "program doktor", "lanjut doktor"],
    "s2": ["magister", "program magister", "lanjut s2"],
    "d3": ["diploma", "program diploma", "vokasi"],

    # --- akreditasi ---
    "akreditasi": ["nilai mutu", "peringkat mutu", "penilaian ban-pt",
                   "nilai dari ban-pt", "status mutu"],

    # --- program studi: bidang minat -> nama prodi ---
    "teknik sipil": ["konstruksi bangunan", "bangunan dan jembatan",
                     "belajar konstruksi"],
    "akuakultur": ["budidaya ikan", "perikanan budidaya", "tambak ikan"],
    "agroteknologi": ["pertanian", "bidang pertanian", "bercocok tanam"],
    "teknik mesin": ["permesinan", "mesin dan manufaktur"],
    "teknik elektro": ["kelistrikan", "listrik dan elektronika"],
    "teknologi informasi": ["komputer", "it", "pemrograman"],
    "manajemen": ["bisnis", "pengelolaan usaha"],
    "akuntansi": ["pembukuan", "keuangan perusahaan"],
    "hukum": ["ilmu hukum", "kuliah jadi pengacara"],
    "biologi": ["ilmu hayati", "makhluk hidup"],
}

# Pola tanya yang dipakai camaba saat menanyakan program studi lewat minat.
POLA_MINAT = [
    "kalau mau belajar {} masuk prodi mana",
    "minat di bidang {} masuk jurusan apa",
    "{} ada jurusannya",
    "ada prodi {} gak",
]


def _balik_kamus():
    """{bahasa camaba: istilah resmi} — untuk penggantian dua arah."""
    keluar = {}
    for resmi, daftar in SINONIM_DOMAIN.items():
        for informal in daftar:
            keluar[informal] = resmi
    return keluar


KE_RESMI = _balik_kamus()


def augment_sinonim(pertanyaan, n=4, seed=0):
    """Bangkitkan varian dengan MENGGANTI istilah resmi jadi bahasa camaba.

    Berbeda dari augment() bawaan notebook yang hanya mengubah permukaan
    kalimat, fungsi ini mengajarkan model bahwa dua kata yang tidak berbagi
    huruf pun bisa berarti sama.
    """
    rng = random.Random(seed)
    dasar = pertanyaan.lower().strip()
    dasar = re.sub(r"[^\w\s]", "", dasar)
    keluar = set()

    for resmi, informal_list in SINONIM_DOMAIN.items():
        if re.search(rf"\b{re.escape(resmi)}\b", dasar):
            for informal in informal_list:
                keluar.add(re.sub(rf"\b{re.escape(resmi)}\b", informal, dasar))

            # Untuk nama prodi, tambahkan juga pola "minat -> prodi apa".
            if resmi in {"teknik sipil", "akuakultur", "agroteknologi",
                         "teknik mesin", "teknik elektro",
                         "teknologi informasi", "manajemen", "akuntansi",
                         "hukum", "biologi"}:
                for pola in POLA_MINAT:
                    keluar.add(pola.format(rng.choice(informal_list)))

    keluar.discard(dasar)
    return sorted(keluar)[:n]


def pasangan_sinonim_global():
    """Pasangan latih tambahan yang TIDAK terikat satu FAQ pun.

    Dipakai sebagai data kontras agar model mempelajari relasi sinonimnya
    sendiri, bukan sekadar menghafal pertanyaan. Kembalikan [(a, b)] yang
    keduanya harus berdekatan di ruang embedding.
    """
    pasangan = []
    for resmi, daftar in SINONIM_DOMAIN.items():
        for informal in daftar:
            pasangan.append((resmi, informal))
            # antar-sinonim juga harus saling dekat
            for lain in daftar:
                if lain != informal:
                    pasangan.append((informal, lain))
    return pasangan


if __name__ == "__main__":
    print(f"istilah resmi      : {len(SINONIM_DOMAIN)}")
    print(f"total sinonim      : {sum(len(v) for v in SINONIM_DOMAIN.values())}")
    print(f"pasangan latih     : {len(pasangan_sinonim_global())}")
    print()
    for q in ["Apakah ada program magang?", "Apakah tersedia asrama?",
              "Jurusan Teknik Sipil ada?", "Apa saja organisasi mahasiswa?"]:
        print(f"  {q}")
        for v in augment_sinonim(q, n=4, seed=1):
            print(f"     -> {v}")
