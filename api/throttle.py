"""Rate limit per IP di tingkat aplikasi.

Lapis kedua setelah Nginx (Bagian 8). Nginx bisa dilewati kalau seseorang
memukul gunicorn langsung, dan di lingkungan dev Nginx memang tidak ada.

Memakai cache Django. Di produksi cache-nya Redis sehingga hitungan dibagi
antar-worker; di dev locmem sehingga per-proses — cukup untuk pengujian.
"""

from __future__ import annotations

from django.core.cache import cache

# Nginx membatasi 20 req/menit. Batas aplikasi dibuat sedikit lebih longgar
# supaya Nginx yang menolak lebih dulu saat keduanya aktif.
BATAS_PER_MENIT = 30
JENDELA_DETIK = 60


def ambil_ip(request) -> str:
    """IP asli klien.

    Tanpa X-Forwarded-For dari Nginx semua request terlihat dari 127.0.0.1
    dan rate limit akan memblokir SELURUH pengguna sekaligus — itu sebabnya
    header ini wajib diteruskan (lihat komentar di deploy/nginx).
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        # Entri paling kiri = klien asli; sisanya rantai proxy.
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "tak-dikenal")


def lewat_batas(request, batas: int = BATAS_PER_MENIT,
                jendela: int = JENDELA_DETIK) -> bool:
    """True bila request ini MELEBIHI batas.

    Kegagalan cache tidak boleh menjatuhkan layanan (prinsip #6) — kalau
    cache mati, biarkan request lewat dan andalkan Nginx.
    """
    kunci = f"throttle:{ambil_ip(request)}"
    try:
        # add() hanya berhasil bila kunci belum ada -> sekaligus set TTL.
        if cache.add(kunci, 1, jendela):
            return False
        jumlah = cache.incr(kunci)
        return jumlah > batas
    except Exception:
        return False
