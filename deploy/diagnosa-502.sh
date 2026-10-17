#!/bin/sh
# Diagnosa 502 Bad Gateway — dijalankan DI VPS.
#
# 502 berarti nginx hidup tapi backend di 127.0.0.1:8000 (API) atau :8001
# (admin) tidak menjawab. Skrip ini hanya MEMBACA, tidak mengubah apa pun,
# jadi aman dijalankan kapan saja.
#
#   sh deploy/diagnosa-502.sh

APP_DIR="${APP_DIR:-/srv/chatbot_ubb}"

garis() { printf '\n──── %s ────\n' "$1"; }

garis "1. Status layanan"
for s in gunicorn-api gunicorn-admin nginx postgresql redis-server; do
    aktif=$(systemctl is-active "$s" 2>/dev/null)
    printf '  %-18s %s\n' "$s" "${aktif:-tidak terpasang}"
done

garis "2. Port didengarkan?"
# 8000 = API, 8001 = admin. Kalau kosong, gunicorn mati atau gagal bind.
if command -v ss >/dev/null; then
    ss -ltnp 2>/dev/null | grep -E ':(8000|8001|80|443)\b' || echo "  ⚠️  TIDAK ADA yang mendengarkan di 8000/8001"
else
    netstat -ltnp 2>/dev/null | grep -E ':(8000|8001|80|443)\b' || echo "  ⚠️  TIDAK ADA yang mendengarkan"
fi

garis "3. Backend menjawab langsung? (lewati nginx)"
for p in 8000 8001; do
    kode=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$p/healthz" 2>/dev/null)
    [ "$p" = 8001 ] && kode=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$p/" 2>/dev/null)
    printf '  127.0.0.1:%s -> HTTP %s\n' "$p" "${kode:-GAGAL TERHUBUNG}"
done

garis "4. Log gunicorn-api (30 baris terakhir)"
journalctl -u gunicorn-api -n 30 --no-pager 2>/dev/null || echo "  (tidak bisa membaca journal)"

garis "5. Log gunicorn-admin (15 baris terakhir)"
journalctl -u gunicorn-admin -n 15 --no-pager 2>/dev/null

garis "6. Error nginx (15 baris terakhir)"
tail -n 15 /var/log/nginx/error.log 2>/dev/null || echo "  (tidak bisa dibaca — coba dengan sudo)"

garis "7. Sumber daya"
echo "  RAM:"; free -h 2>/dev/null | sed 's/^/    /'
echo "  Disk:"; df -h "$APP_DIR" 2>/dev/null | tail -1 | sed 's/^/    /'
# OOM killer adalah penyebab 502 yang paling sering luput: model ~500 MB
# dikali beberapa worker cepat menghabiskan RAM VPS kecil.
echo "  OOM killer baru-baru ini:"
dmesg 2>/dev/null | grep -i "killed process" | tail -3 | sed 's/^/    /' || echo "    (tidak ada / perlu sudo)"

garis "8. Berkas penting"
for f in "$APP_DIR/.env" "$APP_DIR/artifacts/config.json" "$APP_DIR/.venv/bin/gunicorn"; do
    [ -e "$f" ] && echo "  ada     $f" || echo "  HILANG  $f"
done
# Model: symlink menggantung = gunicorn tetap hidup tapi engine None.
if [ -L "$APP_DIR/artifacts/model" ]; then
    tujuan=$(readlink "$APP_DIR/artifacts/model")
    [ -e "$APP_DIR/artifacts/model/" ] \
        && echo "  ada     artifacts/model -> $tujuan" \
        || echo "  ⚠️  SYMLINK MENGGANTUNG artifacts/model -> $tujuan"
elif [ -d "$APP_DIR/artifacts/model" ]; then
    echo "  ada     artifacts/model (direktori)"
else
    echo "  HILANG  artifacts/model"
fi

garis "9. Konfigurasi nginx sah?"
nginx -t 2>&1 | sed 's/^/  /'

garis "Selesai"
echo "Kirimkan seluruh keluaran di atas untuk analisis lebih lanjut."
