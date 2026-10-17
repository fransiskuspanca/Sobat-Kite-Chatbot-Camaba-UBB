#!/bin/sh
# Jalankan admin panel (port 8000 secara bawaan).
#
#   ./jalankan_admin.sh        -> port 8000
#   ./jalankan_admin.sh 9000   -> port 9000

PORT="${1:-8000}"
cd "$(dirname "$0")" || exit 1

# MUAT_MODEL=1 agar cek tabrakan hidup. Ganti ke 0 kalau ingin start cepat.
MUAT_MODEL=1
export MUAT_MODEL

echo "Menjalankan admin panel di port $PORT"
echo "Buka: http://127.0.0.1:$PORT/"
echo

exec .venv/bin/python manage.py runserver "$PORT"
