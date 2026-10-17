#!/bin/sh
# Jalankan server API (port 8001 secara bawaan).
#
# Dibuat sebagai skrip supaya jalan di shell apa pun — tcsh/csh tidak mengenal
# sintaks "VAR=nilai perintah" yang biasa dipakai di bash/zsh.
#
#   ./jalankan_api.sh          -> port 8001
#   ./jalankan_api.sh 9000     -> port 9000

PORT="${1:-8001}"
cd "$(dirname "$0")" || exit 1

MUAT_MODEL=1
DJANGO_SETTINGS_MODULE=config.settings.dev_api
export MUAT_MODEL DJANGO_SETTINGS_MODULE

echo "Menjalankan server API di port $PORT"
echo "Memuat model (~600 MB) — start pertama butuh waktu, sabar…"
echo

exec .venv/bin/python manage.py runserver "$PORT"
