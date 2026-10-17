# Panduan Pengujian Fase 0

Semua perintah dijalankan dari `/Applications/XAMPP/xamppfiles/htdocs/chatbot_pmb_ubb`.

## ⚠️ Baca ini dulu — dua kesalahan paling umum

**1. `manage.py` bukan perintah shell.** Ia berkas Python, jadi harus dipanggil
oleh interpreter Python. Selalu tulis `.venv/bin/python` di depannya:

```bash
manage.py tanya                      # ❌ Command not found
.venv/bin/python manage.py tanya     # ✅
```

**2. Harus `cd` dulu ke folder proyek.** `manage.py` hanya ada di sana:

```bash
cd /Applications/XAMPP/xamppfiles/htdocs/chatbot_pmb_ubb
.venv/bin/python manage.py tanya
```

**Kenapa `.venv/bin/python`, bukan `python3`?** `python3` di Mac ini versi 3.9,
sedangkan proyek butuh 3.12 — dan Django serta torch hanya terpasang di dalam
`.venv`. Memakai `python3` biasa menghasilkan `ModuleNotFoundError: No module
named 'django'`.

### Cara singkat (opsional)

Aktifkan venv sekali di awal sesi, lalu cukup ketik `python`:

```bash
cd /Applications/XAMPP/xamppfiles/htdocs/chatbot_pmb_ubb
source .venv/bin/activate       # tcsh: source .venv/bin/activate.csh
python manage.py tanya
deactivate                      # keluar
```

Prompt akan berawalan `(.venv)` sebagai penanda.

---

## Persiapan (sekali saja)

Kalau Anda memulai dari nol atau ingin mengulang dari bersih:

```bash
cd /Applications/XAMPP/xamppfiles/htdocs/chatbot_pmb_ubb

rm -f db.sqlite3                       # opsional: mulai dari database kosong
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_colab "/Users/macbook/Downloads/Daftar Pertanyaan NLP Chatbot Camaba 2026 UBB.xlsx"
.venv/bin/python manage.py siapkan_model
.venv/bin/python manage.py reindex --paksa
```

`--paksa` diperlukan **untuk sekarang** karena `artifacts/model/` masih model
dasar, bukan hasil fine-tuning — lihat bagian "Kenapa butuh --paksa" di bawah.

---

## 1. Uji otomatis — paling cepat

```bash
.venv/bin/python -m pytest
```

Harapan: **369 passed** (sekitar 30 detik — tes admin memakai database
sementara). Tidak butuh model dan tidak butuh internet.

Bagian yang paling penting di antaranya:

```bash
# Pagar text.py — kalau ini merah, JANGAN deploy
.venv/bin/python -m pytest tests/test_normalisasi.py -v

# Empat tier
.venv/bin/python -m pytest tests/test_tiers.py -v

# Bukti retrieval/ tidak mengenal Django
.venv/bin/python -m pytest tests/test_isolasi_retrieval.py -v
```

---

## 2. Uji manual — mode interaktif ⭐

Cara paling enak menguji. Ketik seperti camaba sungguhan:

```bash
.venv/bin/python manage.py tanya
```

```
camaba> berapa ukt teknik informatika
camaba> min kapan pendaftaran dibuka ya kak
camaba> keluar
```

Sekali tanya tanpa masuk mode interaktif:

```bash
.venv/bin/python manage.py tanya "apa itu snbp"
.venv/bin/python manage.py tanya --detail "berapa biaya kuliah"   # + skor kandidat
```

### Empat tier yang harus Anda lihat

Setiap tier punya warna sendiri di terminal:

| Coba ketik | Harusnya | Arti |
|---|---|---|
| `apa itu ubb` | 🟢 **JAWABAN** (0.99) | Yakin → isi dari database, apa adanya |
| `halo` | 🔵 **SAPAAN** | Tidak menyentuh pencarian sama sekali |
| `resep rendang padang` | 🔴 **FALLBACK** (0.18) | Di luar domain → menolak, tidak menebak |
| `berapa luas kampus` | 🟣 **ESKALASI** (0.99) | **Cocok tapi jawabannya belum terverifikasi** |

**Tier ESKALASI paling penting untuk Anda perhatikan.** Skornya 0.99 — model
sangat yakin menemukan FAQ yang tepat. Tapi jawaban di database berbunyi
*"Perlu wawancara. (Tidak ditemukan angka resmi…)"*, jadi sistem **mengganti**
isinya dengan pesan eskalasi. Placeholder itu tidak pernah sampai ke camaba.
Inilah prinsip #4 yang bekerja. Ada 70 entri seperti ini dari 260.

Untuk melihat sendiri kalau jawaban aslinya memang disembunyikan:

```bash
.venv/bin/python manage.py shell -c "
from faq.models import Faq
f = Faq.objects.get(pertanyaan='Berapa luas kampus?')
print('Isi database :', f.jawaban)
print('butuh_verifikasi:', f.butuh_verifikasi)"
```

---

## 3. Uji data hasil impor

```bash
.venv/bin/python manage.py shell -c "
from faq.models import Faq
print('Total FAQ        :', Faq.objects.count())
print('Butuh verifikasi :', Faq.objects.filter(butuh_verifikasi=True).count())
print('Kategori         :', Faq.objects.values('kategori').distinct().count())"
```

Harapan: **260 / 70 / 29** — cocok dengan angka di dokumen rencana.

Impor tanpa menulis apa pun (untuk mengecek berkas Excel baru):

```bash
.venv/bin/python manage.py import_colab "berkas.xlsx" --dry-run
```

---

## 4. Uji regression gate ⭐

Ini pengaman yang mencegah index buruk terpasang. Jalankan **tanpa** `--paksa`:

```bash
.venv/bin/python manage.py reindex
```

Harapan — gate **menolak**:

```
Acc@1 0.139 < ambang 0.85 — DITOLAK, versi lama tetap melayani
CommandError: Regression gate GAGAL — versi lama tetap melayani.
```

Buktikan tidak ada yang tertulis ke database:

```bash
.venv/bin/python manage.py shell -c "
from faq.models import IndexVersion
print('versi tersimpan:', IndexVersion.objects.count())
print('aktif          :', IndexVersion.objects.filter(aktif=True).count())"
```

### Kenapa butuh `--paksa`

`artifacts/model/` saat ini berisi **model dasar** `LazarusNLP/all-indo-e5-small-v4`,
bukan hasil fine-tuning — notebook Colab belum pernah dijalankan sampai sel
ekspor. Model dasar belum belajar bahasa camaba, jadi Acc@1 hanya 0,139.

**Gate menolak itu perilaku yang benar, bukan bug.** Setelah `artifacts/model/`
diganti hasil fine-tuning, Acc@1 semestinya ≥ 0,85 dan `reindex` biasa akan
lolos tanpa `--paksa`.

---

## 5. Uji backup

```bash
.venv/bin/python manage.py backup_kb
head -30 backup/kb-*.json
```

---

---

# Fase 1 — Admin Panel

## Menjalankan panel

```bash
cd /Applications/XAMPP/xamppfiles/htdocs/chatbot_pmb_ubb

# sekali saja: buat akun & peran
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py siapkan_peran
.venv/bin/python manage.py collectstatic --noinput

# jalankan (MUAT_MODEL=1 supaya cek tabrakan hidup)
MUAT_MODEL=1 .venv/bin/python manage.py runserver
```

Buka **http://127.0.0.1:8000/admin/** lalu login.

> `MUAT_MODEL=1` memuat model ~600 MB, jadi start pertama agak lama. Tanpa itu
> panel tetap jalan, hanya cek tabrakan yang diam (sesuai prinsip #6 — engine
> mati tidak menghalangi panitia bekerja).

## Yang perlu dicoba

### 1. Daftar kerja 70 jawaban ⭐

Sidebar → **Menunggu persetujuan unit**. Inilah penyumbat sesungguhnya sebelum
go-live: 70 dari 260 jawaban masih placeholder "Perlu wawancara".

Coba pilih beberapa baris → aksi **"Tandai TERVERIFIKASI"** → Jalankan.
`terakhir_diverifikasi` terisi otomatis hari ini.

### 2. Pratinjau "seperti apa camaba melihatnya" ⭐

Buka FAQ mana pun yang masih menunggu persetujuan (mis. *Berapa luas kampus?*).
Di bawah kolom Jawaban ada kotak pratinjau — isinya **pesan eskalasi**, bukan
jawaban yang Anda ketik, dengan catatan kuning yang menjelaskan kenapa.

Buka FAQ yang sudah terverifikasi: pratinjau menampilkan jawaban asli lengkap
dengan baris `📎 Sumber:`.

### 3. Cek tabrakan ⭐ (fitur paling penting)

Tambah FAQ baru dengan pertanyaan yang mirip entri lama, contoh:
*"UBB itu universitas apa?"*

Setelah Simpan, muncul peringatan kuning:

> Sangat mirip dengan **"Apa itu Universitas Bangka Belitung?"** (kemiripan 0.94).
> Pertimbangkan menambahkannya sebagai **variasi cara bertanya**…

Entri **tetap tersimpan** — ini peringatan, bukan blokir. Dua entri yang mirip
membuat retrieval ambigu selamanya, jadi lebih murah dicegah di titik input.

### 4. Variasi cara bertanya

Di form FAQ, gulir ke bawah — ada 3 baris kosong siap diisi. Tambahkan
parafrase seperti *"ubb tuh kampus apa sih"*. Kolom **Variasi** di daftar
berwarna: merah (0), kuning (1-2), hijau (≥3 — target go-live).

### 5. Antrean konten

Sidebar → **Antrean konten**. Sekarang masih kosong karena API belum ada
(Fase 2). Untuk melihat cara kerjanya, buat log palsu:

```bash
.venv/bin/python manage.py shell -c "
from percakapan.models import ChatLog
for i in range(5):
    ChatLog.objects.create(log_id=f'uji{i}', query='berapa ukt teknik mesin',
                           tipe='fallback', skor=0.61)
for i in range(3):
    ChatLog.objects.create(log_id=f'uji1{i}', query='kapan pengumuman mandiri',
                           tipe='fallback', skor=0.58)
print('log uji dibuat')"
```

Muat ulang halaman: pertanyaan muncul terurut frekuensi, dengan tombol
**+ Buat FAQ** yang membuka form baru dengan pertanyaan **sudah terisi**.

Hapus log uji setelah selesai:

```bash
.venv/bin/python manage.py shell -c "
from percakapan.models import ChatLog
print(ChatLog.objects.filter(log_id__startswith='uji').delete())"
```

### 6. Peran pengguna

```bash
.venv/bin/python manage.py shell -c "
from django.contrib.auth.models import User, Group
u = User.objects.create_user('staf_pmb', password='cobadulu123', is_staff=True)
u.groups.add(Group.objects.get(name='Editor Konten'))
print('dibuat: staf_pmb / cobadulu123')"
```

Login sebagai `staf_pmb` di jendela penyamaran. Perhatikan: aksi
**"Tandai TERVERIFIKASI" tidak muncul** — menyetujui jawaban adalah kewenangan
Verifikator (kepala unit), bukan editor.

| Peran | Boleh |
|---|---|
| **Editor Konten** | CRUD FAQ & variasi, lihat antrean |
| **Verifikator** | + menyetujui jawaban |
| **Operator** | + reindex, rollback, akses log |

### 7. Perbaikan tampilan

- **Logo UBB** tampil di sidebar kiri-atas, halaman login, dan favicon tab.
- **Tombol aksi** di daftar FAQ: entri yang menunggu unit dapat tombol oranye
  **✎ Lengkapi**, yang sudah final dapat **✎ Edit** — langsung dari daftar,
  tanpa membuka detail dulu.
- **Buka `http://127.0.0.1:8000/`** tanpa `/admin` — otomatis diarahkan ke
  panel (ke login bila belum masuk, ke dashboard bila sudah).
- **Halaman tambah pengguna** (`/admin/auth/user/add/`) kini bergaya unfold;
  sebelumnya memakai template polos Django sehingga isian nyaris tak terlihat.
- **Halaman login** memakai card putih ber-shadow lembut di atas latar abu-abu.
- **Header sidebar** menampilkan nama "Chatbot PMB UBB" dan "Universitas
  Bangka Belitung" di samping logo.
- **Halaman Versi index** kini hanya terlihat oleh Operator. Panitia PMB tidak
  perlu melihat istilah teknis seperti Acc@1 dan vektor.

### Kenapa halaman Versi index tetap ada

Tabel `IndexVersion` menyimpan **vektor index** (~400 KB) — bukan sekadar
catatan, tapi otak chatbot itu sendiri. Halamannya punya satu fungsi yang tidak
tergantikan: **rollback** saat chatbot menjawab ngawur setelah update.

Kolom **Acc@1** adalah skor regression gate: dari sekian pertanyaan uji, berapa
persen yang jawaban teratasnya benar. Ambangnya 0,85. Angka inilah yang di
Fase 0 menolak memasang index buruk (Acc@1 = 0,139 karena masih model dasar) —
tanpa kolom ini, index buruk akan terpasang diam-diam dan camaba menerima
jawaban salah tanpa ada yang tahu penyebabnya.

## Uji otomatis Fase 1

```bash
.venv/bin/python -m pytest tests/test_admin_fase1.py -v
```

```bash
.venv/bin/python -m pytest tests/test_perbaikan_admin.py -v
```

31 + 17 tes: halaman terbuka, aksi massal, peran, cek tabrakan, pratinjau,
kolom kedaluwarsa, logo, tombol aksi, form pengguna, pengalihan root.

---

# Fase 2 — API

## Menjalankan API

Proses API memakai urlconf terpisah (`config.urls_api`) — `/admin/*` tidak
terjangkau dari sana sama sekali.

**Cara termudah — pakai skrip (jalan di shell apa pun):**

```
cd /Applications/XAMPP/xamppfiles/htdocs/chatbot_pmb_ubb
./jalankan_api.sh
```

Bawaannya port 8001. Untuk port lain: `./jalankan_api.sh 9000`.

<details>
<summary>Kalau ingin mengetik perintahnya langsung</summary>

Sintaksnya **berbeda per shell**:

```bash
# bash / zsh / sh
MUAT_MODEL=1 DJANGO_SETTINGS_MODULE=config.settings.dev_api \
  .venv/bin/python manage.py runserver 8001
```

```
# tcsh / csh — WAJIB pakai setenv, satu per baris
setenv MUAT_MODEL 1
setenv DJANGO_SETTINGS_MODULE config.settings.dev_api
.venv/bin/python manage.py runserver 8001
```

Di tcsh, `VAR=nilai perintah` **tidak dikenal** dan menghasilkan:

```
MUAT_MODEL=1: Command not found.
```

Cek shell Anda dengan `echo $0` atau `ps -p $$`.

</details>

> Django **tidak** membaca env var `DJANGO_URLCONF` — urlconf harus datang dari
> settings. Itulah guna `config.settings.dev_api`.
>
> Start pertama memakan waktu (memuat model ~600 MB); request berikutnya
> 30–50 ms. Inilah alasan `preload_app=True` di gunicorn.

### ⚠️ Admin dan API adalah dua server berbeda

Ini sumber kebingungan yang paling sering. Keduanya **tidak bisa dilayani satu
proses** — memang begitu rancangannya (Bagian 3: isolasi keamanan).

| Mau menguji | Perintah | Port |
|---|---|---|
| **Admin panel** | `./jalankan_admin.sh` | 8000 |
| **API** | `./jalankan_api.sh` | 8001 |

Kedua skrip jalan di bash, zsh, maupun tcsh. Untuk memakai keduanya
bersamaan, buka dua terminal.

Kalau `DJANGO_SETTINGS_MODULE` lupa disertakan, yang jalan adalah **admin**,
dan `/v1/chat/query` akan menjawab **404 berupa halaman HTML**. Gejalanya:

```
Expecting value: line 1 column 1 (char 0)
```

Itu bukan error API — itu `python3 -m json.tool` menerima HTML, bukan JSON.

**Cara cepat memastikan server mana yang jalan:**

```bash
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/healthz
```

`200` = server API. `404` = server admin.

Untuk menjalankan keduanya sekaligus, pakai dua terminal dengan port berbeda.

## Endpoint

| Metode | Path | Keterangan |
|---|---|---|
| POST | `/v1/chat/query` | Tanya chatbot |
| POST | `/v1/chat/feedback` | Kirim 👍/👎 |
| GET | `/v1/chat/health` | 503 bila model belum siap |
| GET | `/healthz` | Cek ringan Nginx, tanpa sentuh model |

## Uji keempat tier

```bash
# Sesuaikan port dengan server API Anda (contoh di sini 8001)
curl -s localhost:8001/v1/chat/query -H 'Content-Type: application/json' \
  -d '{"query":"apa itu ubb"}' | python3 -m json.tool
```

Kalau muncul `Expecting value: line 1 column 1`, buang `| python3 -m json.tool`
untuk melihat balasan mentahnya — hampir selalu halaman 404 HTML karena yang
jalan adalah server admin, bukan API.

| Query | Tipe | Arti |
|---|---|---|
| `apa itu ubb` | `jawaban` | Isi dari database, apa adanya |
| `halo` | `sapaan` | Tidak menyentuh pencarian |
| `resep rendang padang` | `fallback` | Di luar domain → menolak |
| `berapa luas kampus` | `eskalasi` | Cocok tapi belum terverifikasi |

Response menyertakan jejak audit (prinsip #2): `answer_id`, `sumber`,
`terakhir_diverifikasi`, plus `log_id`, `index_version`, dan `latency_ms`.

## Uji rate limit

```bash
for i in $(seq 1 40); do
  curl -s -o /dev/null -w "%{http_code} " localhost:8000/v1/chat/query \
    -H 'Content-Type: application/json' -d '{"query":"halo"}'
done; echo
```

Setelah ~30 permintaan per menit muncul `429`.

## Uji CORS

```bash
curl -s -i -X OPTIONS localhost:8000/v1/chat/query \
  -H 'Origin: https://pmb.ubb.ac.id' \
  -H 'Access-Control-Request-Method: POST' | grep -i access-control
```

Origin `pmb.ubb.ac.id` diizinkan; origin lain tidak mendapat header sama sekali.

## Antrean konten kini terisi sendiri

Setiap query yang gagal dijawab tercatat di `ChatLog` dan langsung muncul di
**Antrean konten** admin — tidak perlu lagi membuat log palsu.

---

# Fase 3 — Reindex & Regression Gate

Halaman **Versi index** (sidebar, hanya Operator) kini punya tombol.

## Alur yang paling penting

1. Tambah atau ubah FAQ di admin
2. Buka **Versi index** → klik **⟳ Bangun Ulang Index**
3. Tunggu — halaman memperbarui statusnya sendiri, aman ditinggal
4. Pertanyaan baru langsung terjawab, **tanpa restart server**

Reindex berjalan di thread terpisah, jadi browser tidak menggantung 20-40 detik.

## Regression gate

Sebelum dipasang, index kandidat diuji terhadap `artifacts/hard_eval.json`:

- **Acc@1 ≥ 0,85** → dipasang, versi naik
- **Acc@1 < 0,85** → **DITOLAK**, versi lama tetap melayani, entri penyebab
  ditampilkan di halaman

Halaman menyatakan dengan jelas apakah gate aktif — kalau `hard_eval.json`
tidak ada, muncul peringatan kuning agar tidak ada yang mengira terlindungi.

> Dengan model dasar Acc@1 = 0,139, jadi gate **akan menolak**. Itu benar.
> Untuk pengujian, pakai `--paksa` di CLI.

## Rollback

Setiap versi non-aktif punya tombol **↩ Rollback**. Tidak ada encode ulang —
vektornya sudah tersimpan di basis data, jadi pemulihan seketika.

Ini langkah pertama di runbook saat chatbot menjawab ngawur setelah update.

## Lewat baris perintah

```bash
.venv/bin/python manage.py reindex              # dengan gate
.venv/bin/python manage.py reindex --paksa      # abaikan gate
.venv/bin/python manage.py reindex --rollback 1 # kembali ke v1
```

CLI dan tombol admin memakai jalur kode yang sama (`faq/actions.py`).

## Deteksi versi antar-worker

Dengan 3 worker, reindex dari proses admin tidak otomatis terlihat worker API.
Setiap worker memeriksa versi aktif tiap 10 detik (query sangat murah) dan
memuat ulang bila berbeda — jadi perubahan menyusul sendiri dalam hitungan
detik, tanpa restart.

---

# Fase 4 — Produksi

Berkas deploy ada di `deploy/`. Semuanya untuk **VPS Ubuntu 24.04**, bukan
untuk dijalankan di laptop.

## Berkas

| Berkas | Guna |
|---|---|
| `deploy/nginx/01-sebelum-tls.conf` | Tahap 1: HTTP saja, jalan masuk certbot |
| `deploy/nginx/02-sesudah-tls.conf` | Tahap 2: HTTPS + rate limit + allowlist admin |
| `deploy/systemd/gunicorn-*.service` | Dua layanan: API :8000, admin :8001 |
| `deploy/gunicorn_*.py` | `preload_app`, `max_requests`, timeout |
| `deploy/backup.sh` | pg_dump + JSON + rclone keluar VPS |
| `deploy/deploy.sh` | git pull → migrate → collectstatic → reload |
| `deploy/cron-chatbot` | Backup harian, bersih log, pengingat FAQ |

## Urutan pemasangan di VPS

```sh
# 1. Penguatan server (Bagian 10.1) — sebagai root
adduser deploy && usermod -aG sudo deploy
chown -R deploy:deploy /srv/chatbot_ubb
ufw default deny incoming && ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable
apt install unattended-upgrades fail2ban nginx

# 2. DNS: A-record api. dan admin. -> IP VPS

# 3. Aplikasi — WAJIB sebagai user deploy (lihat catatan $HOME di bawah)
su - deploy
cd /srv/chatbot_ubb
cp .env.example .env      # ISI DJANGO_SECRET_KEY!
.venv/bin/pip install -e ".[prod]"
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_colab kb-awal.json
.venv/bin/python manage.py siapkan_model
.venv/bin/python manage.py reindex --paksa
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py siapkan_peran
exit

# 4. Nginx TAHAP 1 — HTTP saja, supaya certbot punya jalan masuk
sudo cp deploy/nginx/01-sebelum-tls.conf /etc/nginx/sites-available/chatbot-ubb
sudo ln -sf /etc/nginx/sites-available/chatbot-ubb /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 5. TLS
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/bin/certbot
sudo certbot --nginx -d api.chatbot-ubb.tech -d admin.chatbot-ubb.tech

# 6. Nginx TAHAP 2 — HTTPS penuh + rate limit
sudo cp deploy/nginx/02-sesudah-tls.conf /etc/nginx/sites-available/chatbot-ubb
sudo nginx -t && sudo systemctl reload nginx

# 7. Layanan
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gunicorn-api gunicorn-admin
sudo cp deploy/cron-chatbot /etc/cron.d/chatbot-ubb
```

### ⚠️ Dua jebakan yang pasti ditemui

**1. Jalankan semua perintah aplikasi sebagai user `deploy`.**

```sh
su - deploy      # tanda minus WAJIB
whoami           # harus: deploy
echo $HOME       # harus: /home/deploy
```

Kalau `$HOME` berbunyi `/nonexistent`, perintah dijalankan sebagai user sistem
tanpa home directory. Gejalanya:

```
WARNING: The directory '/nonexistent/.cache/pip' ... is not writable
CommandError: Gagal mengunduh model: [Errno 13] Permission denied: '/nonexistent'
```

**2. Nginx dipasang dua tahap.**

Nginx tidak bisa start dengan `listen 443 ssl` bila sertifikatnya belum ada,
padahal certbot butuh Nginx hidup untuk verifikasi. Karena itu config dipisah:
`01-sebelum-tls.conf` (HTTP saja) → certbot → `02-sesudah-tls.conf`.

Config memakai `listen 443 ssl http2;`, bukan `http2 on;` — sintaks kedua
hanya dikenal Nginx ≥ 1.25 dan membuat Ubuntu 24.04 (Nginx 1.24) gagal dengan
`unknown directive "http2"`.

## Cek keamanan sebelum go-live

```bash
DJANGO_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(64))')" \
DJANGO_SETTINGS_MODULE=config.settings.prod_api \
  .venv/bin/python manage.py check --deploy
```

Harus **"no issues"**. Kalau ada peringatan, jangan deploy.

## Perintah terjadwal

```bash
.venv/bin/python manage.py bersihkan_log --dry-run     # log > 12 bulan
.venv/bin/python manage.py ingatkan_kedaluwarsa        # FAQ perlu verifikasi ulang
```

## Backup & restore

```bash
.venv/bin/python manage.py backup_kb        # ekspor JSON
./deploy/backup.sh                          # di VPS: pg_dump + rclone
```

Uji restore sudah **otomatis** di `tests/test_fase4_produksi.py` — termasuk
memastikan flag `butuh_verifikasi` terjaga, karena kalau hilang saat restore,
70 placeholder akan bocor ke publik.

> Backup yang tersimpan di server yang sama dengan datanya **bukan backup**.
> Langkah rclone wajib, bukan opsional.

## Monitoring

- **Ekspor Excel** — aksi massal di daftar FAQ; panitia bisa mengunduh salinan
- **Statistik** — sidebar; yang perlu diawasi: **rasio tidak terjawab**
  (menyala merah bila > 25%)
- **Sentry** — isi `SENTRY_DSN` di `.env`; kosongkan untuk mematikan
- **UptimeRobot** — pantau `https://api.chatbot-ubb.tech/healthz` tiap 5 menit

---

## Ringkasan perintah

| Perintah | Kegunaan |
|---|---|
| `pytest` | 369 tes otomatis |
| `manage.py tanya` | Mode interaktif ⭐ |
| `manage.py tanya "..." --detail` | Sekali tanya + skor kandidat |
| `manage.py import_colab <berkas> [--dry-run]` | Excel/JSON → database |
| `manage.py siapkan_model` | Unduh model dasar (symlink) |
| `manage.py reindex [--paksa]` | Bangun index + regression gate |
| `manage.py reindex --rollback N` | Kembali ke versi index lama |
| `manage.py backup_kb` | Ekspor basis pengetahuan |
| `manage.py bersihkan_log` | Hapus log > 12 bulan |
| `manage.py ingatkan_kedaluwarsa` | Laporan FAQ perlu verifikasi ulang |
| `manage.py siapkan_peran` | Buat 3 grup peran pengguna |
| `manage.py runserver` | Jalankan admin panel |

---

## Yang BELUM ada di Fase 0

Ini normal — sesuai roadmap, dikerjakan per fase:

- ~~**Admin panel** (Fase 1)~~ — ✅ selesai
- ~~**API HTTP** (Fase 2)~~ — ✅ selesai
- ~~**Tombol reindex di admin** (Fase 3)~~ — ✅ selesai
