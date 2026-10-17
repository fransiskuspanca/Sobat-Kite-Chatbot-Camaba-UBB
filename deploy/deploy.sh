#!/bin/sh
# Urutan deploy (Bagian 10.6).
#
# `systemctl reload` pada gunicorn memulai worker baru sebelum mematikan yang
# lama, jadi camaba tidak melihat error. Restart penuh hanya perlu bila model
# atau preload_app berubah.

set -e

APP_DIR="${APP_DIR:-/srv/chatbot_ubb}"
cd "$APP_DIR"

# manage.py default-nya config.settings.dev — dan dev memakai SQLite. Tanpa
# baris ini, `migrate` merapikan db.sqlite3 yang TIDAK pernah dipakai produksi,
# lapor sukses, sementara PostgreSQL yang dilayani gunicorn tetap tanpa tabel.
# Kredensial DB juga dibaca dari .env, jadi .env harus dimuat lebih dulu.
set -a
. "$APP_DIR/.env"
set +a
export DJANGO_SETTINGS_MODULE=config.settings.prod_admin

echo "[1/5] git pull…"
git pull

echo "[2/5] dependensi…"
.venv/bin/pip install -q -e ".[prod]"

echo "[3/5] migrasi…"
.venv/bin/python manage.py migrate --noinput

echo "[4/5] static…"
.venv/bin/python manage.py collectstatic --noinput

echo "[5/5] muat ulang layanan…"
# HARUS restart, bukan reload. Dengan preload_app=True (deploy/gunicorn_api.py)
# model dimuat di master SEBELUM fork; `reload` mengirim HUP yang hanya
# mencabangkan ulang worker dari master LAMA, jadi kode dan model lama tetap
# terpakai dan deploy terlihat sukses padahal tidak ada yang berubah.
sudo systemctl restart gunicorn-api
sudo systemctl restart gunicorn-admin

echo
echo "Menunggu health check…"
# Gunicorn API memuat model saat start; `sleep 3` sering terlalu cepat dan
# membuat deploy lapor gagal padahal layanan baik-baik saja. Coba berulang.
n=0
until curl -fsS http://127.0.0.1:8000/healthz >/dev/null; do
    n=$((n + 1))
    if [ "$n" -ge 30 ]; then
        echo "❌ API TIDAK merespons setelah 60 detik."
        echo "   Cek: journalctl -u gunicorn-api -n 50"
        exit 1
    fi
    sleep 2
done
echo "   proses hidup (/healthz 200)."

# /healthz sengaja TIDAK menyentuh model (config/urls_api.py), jadi ia tetap
# 200 walau engine gagal dimuat — pernah membuat deploy lapor sukses padahal
# chatbot menjawab pesan darurat untuk semua pertanyaan. /v1/chat/health
# membalas 503 bila model atau index belum siap; itu yang benar-benar diuji.
if curl -fsS http://127.0.0.1:8000/v1/chat/health >/dev/null 2>&1; then
    echo "✅ Deploy selesai — API sehat, model & index siap."
else
    echo "⚠️  API hidup TAPI model/index BELUM siap — chatbot akan menjawab"
    echo "    pesan darurat untuk setiap pertanyaan."
    echo "    Rinci : curl -s http://127.0.0.1:8000/v1/chat/health"
    echo "    Log   : journalctl -u gunicorn-api -n 50"
    exit 1
fi
