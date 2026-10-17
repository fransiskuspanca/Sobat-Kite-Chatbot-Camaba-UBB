"""Produksi — lihat Bagian 10.5 dokumen rencana."""

import os

from .base import *  # noqa: F401,F403

DEBUG = False
# 127.0.0.1/localhost ikut diizinkan bukan untuk publik — port gunicorn hanya
# terbuka di loopback (Nginx yang menghadap internet). Tanpa ini health check
# internal (deploy.sh, systemd, UptimeRobot lewat Nginx) mengirim Host
# "127.0.0.1:8000" dan Django menolaknya dengan 400 DisallowedHost.
ALLOWED_HOSTS = ["api.chatbot-ubb.tech", "admin.chatbot-ubb.tech",
                 "127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = ["https://admin.chatbot-ubb.tech"]

# Tanpa ini Django mengira koneksinya HTTP dan menolak menetapkan secure
# cookie — login admin gagal dengan pesan yang membingungkan.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Nginx sudah mengalihkan :80 -> :443, tapi ini pagar keduanya: kalau
# konfigurasi Nginx berubah dan redirect-nya hilang, Django tetap menolak
# melayani lewat HTTP. Widget di pmb.ubb.ac.id WAJIB HTTPS — browser
# memblokir total panggilan HTTP dari halaman HTTPS (mixed content).
SECURE_SSL_REDIRECT = True
# /healthz dikecualikan agar Nginx & UptimeRobot bisa mengecek lewat HTTP
# internal tanpa terkena redirect.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"

# KeyError kalau lupa — itu disengaja.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

MUAT_MODEL = os.environ.get("MUAT_MODEL", "1") == "1"


# Rate limit aplikasi menghitung lewat cache. Dengan 2 worker, cache per-proses
# berarti batas efektifnya berlipat — Redis membuat hitungan dibagi bersama.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/1"),
    }
}


# --- Sentry (Bagian 11.3) -------------------------------------------------
# Jauh lebih berguna daripada membaca log manual. Opsional: kalau SENTRY_DSN
# tidak diisi, seluruh blok ini dilewati tanpa error.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration()],
            # Skala ini kecil; 10% cukup untuk melihat pola latensi.
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES", "0.1")),
            send_default_pii=False,      # pertanyaan camaba tidak dikirim utuh
            environment=os.environ.get("SENTRY_ENV", "produksi"),
        )
    except ImportError:
        import warnings
        warnings.warn("SENTRY_DSN diisi tapi sentry-sdk belum terpasang.")
