#!/bin/sh
# Backup harian basis pengetahuan.
#
# Basis pengetahuan adalah hasil kerja berbulan-bulan mengurasi 260 FAQ, dan
# satu VPS berarti TIDAK ADA redundansi. Skrip ini membuat dua bentuk:
#   1. pg_dump  — pemulihan penuh
#   2. JSON     — bisa dibaca manusia & diimpor ulang lewat import_colab
#
# Backup yang tersimpan di server yang sama dengan datanya BUKAN backup:
# langkah rclone di bawah wajib, bukan opsional.

set -e

APP_DIR="${APP_DIR:-/srv/chatbot_ubb}"
BACKUP_DIR="${BACKUP_DIR:-/backup}"
DB_NAME="${DB_NAME:-chatbot}"
DB_USER="${DB_USER:-ubb}"
RETENSI_HARI="${RETENSI_HARI:-30}"
TANGGAL=$(date +%F)

mkdir -p "$BACKUP_DIR"

echo "[1/3] pg_dump…"
pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_DIR/kb-$TANGGAL.sql.gz"

echo "[2/3] ekspor JSON…"
cd "$APP_DIR"
.venv/bin/python manage.py backup_kb --keluar "$BACKUP_DIR/kb-$TANGGAL.json"

echo "[3/3] salin keluar VPS…"
if command -v rclone >/dev/null 2>&1; then
    rclone copy "$BACKUP_DIR/" gdrive:backup-chatbot/ --max-age 2d
else
    echo "  ⚠️  rclone tidak terpasang — backup HANYA ada di VPS ini."
    echo "     Itu bukan backup. Pasang rclone dan konfigurasikan remote."
fi

echo "Membersihkan backup > $RETENSI_HARI hari…"
find "$BACKUP_DIR" -name 'kb-*.sql.gz' -mtime "+$RETENSI_HARI" -delete
find "$BACKUP_DIR" -name 'kb-*.json'   -mtime "+$RETENSI_HARI" -delete

echo "✅ Backup $TANGGAL selesai."
