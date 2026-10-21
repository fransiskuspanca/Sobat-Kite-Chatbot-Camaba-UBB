"""Penjaga domain: jangan menjawab dengan yakin bila kata-katanya tidak nyambung.

Skor kosinus model embedding kecil tidak memisahkan pertanyaan di luar topik
dengan baik: "apa resep nasi goreng?" bisa mendapat skor di atas tau_high
terhadap FAQ biaya kuliah, lalu dijawab dengan yakin. Menaikkan ambang skor
saja ikut menolak pertanyaan sah, jadi penjaga ini bekerja di sisi kata.

Dua pemeriksaan, keduanya memakai kosakata dari pertanyaan kanonik + seluruh
variasi FAQ (bukan jawabannya):

1. Di luar domain: pertanyaan tidak memuat SATU PUN kata isi yang dikenal
   kosakata seluruh FAQ ("resep nasi goreng").
2. Tidak nyambung: FAQ teratas tidak berbagi satu pun kata isi dengan
   pertanyaan ("berapa jumlah lulusan" -> FAQ penentuan kelompok UKT).

Kata tanya dan basa-basi umum tidak dihitung. Bentuk berimbuhan dan salah
ketik satu huruf pada kata panjang tetap dikenali supaya pertanyaan sah tidak
ikut tertolak. Penjaga tanpa entri tidak pernah menolak apa pun.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from .text import normalize

# Kata yang muncul di pertanyaan apa pun, di dalam maupun di luar domain.
# Kata-kata ini TIDAK dihitung sebagai bukti bahwa pertanyaan menyangkut PMB.
KATA_UMUM = frozenset("""
ada adakah adalah agak agar aja ajah akan aku amat anda apa apaan apakah apasih atau
ayo bagaimana bagaimanakah bagi bahwa baik banget bantu bantuin begitu begini belum
benar benarkah beri berikan berapa berapakah bikin bisa bisakah boleh bolehkah buat
buatkan bukan cara caranya cek coba cuma dah dalam dan dapat dapet dari daripada deh di
dengan dimana dong dulu emang emangnya engga enggak entar ga gak gaes gan gimana gitu gk
gua gue guys hal halo hanya harus hey hi hai ingin ini itu iya jadi jangan jawab jelaskan
jika juga kah kak kakak kalau kalo kami kamu kan kapan kasih kata ke kenapa kepada ketika
kita klo kok lagi lah lalu langsung lebih lho loh mah mana mas mau maaf makasih masih mbak
membuat memang mengapa mohon mungkin nah nanti nggak nih nya oh oke ok pak pake pakai
para per perlu permisi pula punya saja sama sampai sangat saya se sebenarnya sebutkan
sedang sekali sekarang seperti sih silakan siapa siapakah sini situ soal sudah supaya
tahu tanya tapi tau tdk tentang terima tetapi tidak tlg tolong tuh untuk wah ya yah yang
yuk arti artinya banyak contoh hari info informasi mengenai paling rekomendasi saran
seputar tadi terbaru
""".split())

_KATA = re.compile(r"[a-z0-9]+")
_AWALAN = ("meng", "meny", "mem", "men", "me", "peng", "peny", "pem", "pen", "pe",
           "ber", "be", "ter", "di", "ke", "se")
_AKHIRAN = ("nya", "kan", "lah", "kah", "an", "i")

FREK_MIN = 2         # kata yang hanya muncul sekali belum dianggap kosakata domain
# Kata yang dipakai lebih dari porsi FAQ ini ("kampus", "mahasiswa", dan
# "universitas bangka belitung" hasil perluasan "ubb") tidak membedakan FAQ
# satu dari yang lain, jadi tidak dihitung sebagai bukti nyambung.
PORSI_UMUM = 0.15
PANJANG_TOLERAN = 6  # salah ketik hanya ditoleransi pada kata sepanjang ini


def _dasar(kata: str) -> str:
    """Pemotong imbuhan kasar. Cukup untuk mencocokkan, bukan untuk linguistik."""
    for a in _AKHIRAN:
        if kata.endswith(a) and len(kata) - len(a) >= 4:
            kata = kata[: -len(a)]
            break
    for a in _AWALAN:
        if kata.startswith(a) and len(kata) - len(a) >= 4:
            kata = kata[len(a):]
            break
    return kata


def _bentuk(kata: str) -> set[str]:
    return {kata, _dasar(kata)}


def _tetangga(kata: str) -> set[str]:
    """Kata dengan satu huruf dihapus: dua kata berjarak edit satu selalu
    berbagi salah satu bentuk ini (atau salah satunya bentuk utuh yang lain)."""
    return {kata[:i] + kata[i + 1:] for i in range(len(kata))}


def kata_isi(teks: str) -> list[str]:
    """Kata isi dari `teks`: dinormalisasi, kata umum dan angka dibuang."""
    return [k for k in _KATA.findall(normalize(teks))
            if len(k) > 1 and k not in KATA_UMUM and not k.isdigit()]


class _Kumpulan:
    """Sekumpulan kata beserta bentuk dasar dan tetangga salah ketiknya."""

    def __init__(self, kata: set[str]):
        self.bentuk = set().union(*map(_bentuk, kata)) if kata else set()
        self.tetangga: set[str] = set()
        for k in self.bentuk:
            if len(k) >= PANJANG_TOLERAN:
                self.tetangga |= _tetangga(k)

    def kenal(self, kata: str) -> bool:
        if _bentuk(kata) & self.bentuk:
            return True
        if len(kata) < PANJANG_TOLERAN:
            return False
        sekitar = _tetangga(kata)
        return bool(kata in self.tetangga or sekitar & self.bentuk
                    or sekitar & self.tetangga)


class PenjagaDomain:
    """Dibangun dari entri index: [{"faq_id": int, "teks": str}, ...]."""

    def __init__(self, entri: list[dict] = ()):
        per_faq: dict[int, set[str]] = defaultdict(set)
        frek: Counter = Counter()
        for e in entri:
            isi = set(kata_isi(e["teks"]))
            per_faq[int(e["faq_id"])] |= isi
            frek.update(isi)
        dikenal = {k for k, n in frek.items() if n >= FREK_MIN}
        self._semua = _Kumpulan(dikenal)
        # Seberapa banyak FAQ memakai tiap bentuk kata (dasar ikut dihitung).
        df: Counter = Counter()
        for isi in per_faq.values():
            df.update(set().union(*map(_bentuk, isi)) if isi else set())
        batas = max(2, PORSI_UMUM * len(per_faq))
        self._pembeda = {k for k in dikenal if all(df[b] <= batas for b in _bentuk(k))}
        self._kata_faq = dict(per_faq)
        self._faq: dict[int, _Kumpulan] = {}

    def __bool__(self) -> bool:
        return bool(self._kata_faq)

    def di_luar_domain(self, query: str) -> bool:
        """True bila `query` punya kata isi tetapi tidak satu pun dikenal.

        Query tanpa kata isi ("apa ya?") tidak diputuskan di sini — biar
        ambang skor biasa yang menanganinya.
        """
        if not self:
            return False
        isi = kata_isi(query)
        return bool(isi) and not any(self._semua.kenal(k) for k in isi)

    def nyambung(self, query: str, faq_id: int) -> bool:
        """Apakah kata pembeda di `query` ada yang dipakai FAQ `faq_id`?

        Kata pembeda = kata domain yang tidak dipakai hampir semua FAQ. Query
        tanpa kata pembeda ("ceritain tentang kampus ini") tidak dinilai.
        """
        if not self or faq_id not in self._kata_faq:
            return True
        isi = [k for k in kata_isi(query) if k in self._pembeda]
        if not isi:
            return True
        if faq_id not in self._faq:
            self._faq[faq_id] = _Kumpulan(self._kata_faq[faq_id])
        return any(self._faq[faq_id].kenal(k) for k in isi)

    def tolak(self, query: str, faq_id: int | None) -> bool:
        """Gabungan kedua pemeriksaan untuk kandidat teratas."""
        if self.di_luar_domain(query):
            return True
        return faq_id is not None and not self.nyambung(query, faq_id)
