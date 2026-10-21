"""Setelan bersama untuk kedua process group (API & admin)."""

import os
from pathlib import Path

from django.templatetags.static import static
from django.urls import reverse_lazy
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-jangan-dipakai-di-produksi")
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    # unfold WAJIB mendahului django.contrib.admin — ia menimpa template admin.
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "faq",
    "percakapan",
    "retrieval",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Harus setinggi mungkin, sebelum CommonMiddleware.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls_admin"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

WSGI_APPLICATION = "config.wsgi_admin.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "chatbot"),
        "USER": os.environ.get("DB_USER", "ubb"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = os.environ.get("STATIC_ROOT", str(BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- retrieval ------------------------------------------------------------
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", BASE_DIR / "artifacts"))

# Boleh menimpa config.json artefak Colab (Lampiran dokumen rencana).
TAU_HIGH = os.environ.get("TAU_HIGH")
TAU_LOW = os.environ.get("TAU_LOW")

# Paket data tambahan hasil simulasi (manage.py sinkron_data).
SINKRON_SUMBER = os.environ.get(
    "SINKRON_SUMBER",
    "https://raw.githubusercontent.com/fransiskuspanca/"
    "Sobat-Kite-Chatbot-Camaba-UBB/main/data/sinkron/")

# Fase 0 belum menjalankan server; model dimuat mulai Fase 2.
MUAT_MODEL = os.environ.get("MUAT_MODEL", "0") == "1"

# --- CORS (Bagian 8) ------------------------------------------------------
# pmb.ubb.ac.id dan api.chatbot-ubb.tech beda origin, jadi SEMUA panggilan
# bersifat lintas-origin dan preflight OPTIONS akan terjadi.
CORS_ALLOWED_ORIGINS = [
    "https://pmb.ubb.ac.id",
    "https://www.ubb.ac.id",       # bila widget disematkan di situs utama
]
# JANGAN CORS_ALLOW_ALL_ORIGINS = True: situs mana pun boleh memakai API ini
# atas biaya VPS Anda.
CORS_ALLOW_CREDENTIALS = False     # tidak perlu cookie; session_id di body
CORS_ALLOW_METHODS = ["GET", "POST", "OPTIONS"]
CORS_PREFLIGHT_MAX_AGE = 3600      # hemat satu roundtrip per sesi
CORS_URLS_REGEX = r"^/(v1|healthz).*$"   # admin tidak pernah lintas-origin

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"ringkas": {"format": "{levelname} {asctime} {name} {message}",
                               "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "ringkas"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}

# --- Tampilan admin (django-unfold) --------------------------------------
# Panitia PMB bukan orang teknis. Label memakai bahasa kerja mereka, bukan
# nama tabel — lihat Bagian 7.6 dokumen rencana.
UNFOLD = {
    "SITE_TITLE": "Chatbot PMB UBB",
    "SITE_HEADER": "Chatbot PMB UBB",
    "SITE_SUBHEADER": "Panel Panitia Penerimaan Mahasiswa Baru",
    "SITE_URL": None,
    # Logo UBB: sidebar kiri-atas, halaman login, dan favicon.
    "SITE_ICON": lambda r: static("img/Logo_UBB.png"),
    "SITE_LOGO": lambda r: static("img/Logo_UBB.png"),
    "SITE_SYMBOL": None,
    "SITE_FAVICONS": [{
        "rel": "icon", "type": "image/png",
        "href": lambda r: static("img/Logo_UBB.png"),
    }],
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "COLORS": {
        # Biru UBB
        "primary": {
            "50": "239 246 255", "100": "219 234 254", "200": "191 219 254",
            "300": "147 197 253", "400": "96 165 250", "500": "59 125 216",
            "600": "37 99 235", "700": "29 78 216", "800": "30 64 175",
            "900": "30 58 138", "950": "23 37 84",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Basis Pengetahuan",
                "separator": False,
                "items": [
                    {"title": "Pertanyaan & Jawaban",
                     "icon": "quiz",
                     "link": lambda r: reverse_lazy("admin:faq_faq_changelist")},
                    {"title": "Menunggu persetujuan unit",
                     "icon": "pending_actions",
                     "link": lambda r: (
                         f"{reverse_lazy('admin:faq_faq_changelist')}"
                         "?butuh_verifikasi__exact=1")},
                    {"title": "Variasi cara bertanya",
                     "icon": "format_quote",
                     "link": lambda r: reverse_lazy(
                         "admin:faq_faqvariasi_changelist")},
                    {"title": "Laporan data simulasi",
                     "icon": "science",
                     "link": lambda r: reverse_lazy("admin:laporan_simulasi")},
                    {"title": "Kata pengantar pembuka",
                     "icon": "waving_hand",
                     "link": lambda r: reverse_lazy(
                         "admin:faq_pengaturansapaan_changelist")},
                ],
            },
            {
                "title": "Percakapan Camaba",
                "separator": True,
                "items": [
                    {"title": "Calon Camaba",
                     "icon": "person",
                     "link": lambda r: reverse_lazy(
                         "admin:percakapan_sesi_changelist")},
                    {"title": "Antrean konten",
                     "icon": "playlist_add",
                     "link": lambda r: reverse_lazy("admin:antrean_konten")},
                    {"title": "Statistik",
                     "icon": "monitoring",
                     "link": lambda r: reverse_lazy(
                         "admin:statistik_percakapan")},
                    {"title": "Log percakapan",
                     "icon": "forum",
                     "link": lambda r: reverse_lazy(
                         "admin:percakapan_chatlog_changelist")},
                ],
            },
            {
                "title": "Sistem",
                "separator": True,
                "items": [
                    # Alat Operator, bukan alat panitia PMB (Bagian 7.5).
                    {"title": "Versi index",
                     "icon": "layers",
                     "link": lambda r: reverse_lazy(
                         "admin:faq_indexversion_changelist"),
                     "permission": lambda r: (
                         r.user.is_superuser
                         or r.user.has_perm("faq.dapat_reindex"))},
                    {"title": "Pengguna",
                     "icon": "group",
                     "link": lambda r: reverse_lazy("admin:auth_user_changelist"),
                     "permission": lambda r: r.user.is_superuser},
                ],
            },
        ],
    },
}
