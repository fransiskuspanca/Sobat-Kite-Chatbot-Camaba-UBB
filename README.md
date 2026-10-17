# Chatbot PMB UBB — Admin Panel & API

Implementasi dari `vibe-planning-chatbot-ubb.md`.

> Model **tidak menulis jawaban**. Model hanya memutuskan **jawaban mana** dari
> basis data yang paling cocok. Isi jawabannya dikirim apa adanya seperti yang
> diketik panitia PMB.

## Status: Fase 4 — Produksi ✅

| Fase | Isi | Status |
|------|-----|--------|
| 0 | Proyek Django, models + migrasi, `import_colab`, `retrieval/` teruji | ✅ selesai |
| 1 | Admin panel (FaqAdmin, cek tabrakan, peran, unfold) | ✅ selesai |
| 2 | API django-ninja, empat tier, CORS, rate limit | ✅ selesai |
| 3 | Reindex, regression gate, rollback | ✅ selesai |
| 4 | Nginx, TLS, systemd, backup, monitoring | ✅ selesai |

> **Cara menguji: lihat [PENGUJIAN.md](PENGUJIAN.md).**

```
./jalankan_admin.sh     # admin panel  -> http://127.0.0.1:8000/
./jalankan_api.sh       # API          -> http://127.0.0.1:8001/v1/
```

## Menjalankan

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"        # atau requirements.txt
cp .env.example .env

.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_colab "FAQ_Sobat_Kite_Fix.xlsx"   # sheet Variasi ikut diimpor
.venv/bin/python -m pytest                # 579 tes
```

Definition of done Fase 0 — pencarian dari shell:

```bash
MUAT_MODEL=1 .venv/bin/python manage.py shell -c "
from retrieval.engine import get_engine
print(get_engine().cari('apa itu ubb'))"
```

## Struktur

```
config/      settings (base/dev/prod), urls_api, urls_admin, wsgi_*
faq/         models, admin.py ⭐, actions.py, services.py, perintah import_colab/reindex/backup_kb/siapkan_peran
retrieval/   text.py ⚠️ · engine.py · indexer.py · tiers.py · apps.py
api/         schemas.py · router.py · throttle.py
percakapan/  Sesi · ChatLog · Feedback · admin.py (antrean konten)
templates/   admin/percakapan/antrean_konten.html
tests/       383 tes; retrieval/ diuji tanpa Django
artifacts/   model/ · config.json · normalisasi_gold.json
```

## API publik

| Endpoint | Guna |
|---|---|
| `POST /v1/chat/session` | Camaba mengisi `nama_lengkap` + `jenis_kelamin` (`L`/`P`), menerima `session_id` |
| `POST /v1/chat/query` | Bertanya; sertakan `session_id`, dikembalikan lagi di response |
| `GET /v1/chat/history?session_id=…` | Riwayat satu sesi (maks 50, terlama lebih dulu) |
| `POST /v1/chat/feedback` | 👍/👎 atas sebuah `log_id` |
| `GET /v1/chat/health` | Kesiapan model & index |

Alur di `pmb.ubb.ac.id`: form nama + jenis kelamin → `POST /session` →
simpan `session_id` ke `localStorage` → sertakan di setiap `/query`.
Saat widget dibuka lagi, `GET /history` memulihkan percakapan; **404 berarti
`localStorage` sudah basi** dan form identitas harus ditampilkan ulang.

`session_id` dibuat SERVER, bukan klien — kalau frontend yang memilih, siapa
pun bisa menebak `session_id` orang lain dan membaca riwayatnya. Ini tetap
bukan token autentikasi: jangan pernah menaruh data sensitif di riwayat.

## Aturan yang tidak bisa ditawar

1. **`retrieval/` tidak mengimpor `faq/` atau `api/`.** Diuji tanpa Django dan tanpa DB.
2. **`retrieval/text.py` identik dengan notebook.** Sudah diverifikasi byte-per-byte.
   Pagarnya `tests/test_normalisasi.py` terhadap `artifacts/normalisasi_gold.json`
   (53 kasus, dibangkitkan dari notebook). **Kalau tes ini merah, jangan deploy.**
3. **Jawaban `butuh_verifikasi` tidak pernah tampil** — diganti pesan eskalasi
   di `retrieval/tiers.py`, diuji di `test_butuh_verifikasi_tidak_pernah_menampilkan_jawaban`.

## Catatan penting untuk Fase berikutnya

- `artifacts/model/` adalah **symlink** ke cache HuggingFace berisi **model
  dasar** (`LazarusNLP/all-indo-e5-small-v4`), bukan hasil fine-tuning —
  notebook belum pernah dijalankan sampai sel ekspor, dan disk laptop penuh.
  Ganti dengan `artifacts/model/` dari Colab sebelum mengukur akurasi.
- `artifacts/hard_eval.json` sudah diekspor dari `HARD_SET` notebook (33
  pertanyaan kanonik, 36 parafrase; semuanya terpetakan ke FAQ nyata).
  Regression gate **aktif** dan sudah terbukti bekerja: dengan model dasar
  Acc@1 = 0.139 dan gate **menolak memasang index** (0 baris ditulis).
  Angka itu akan naik setelah model fine-tuning dipasang.
- Ambang `tau_high=0.72 / tau_low=0.60` di `artifacts/config.json` adalah
  **default sementara**, bukan hasil kalibrasi sel 8.
- Lingkungan dev ini macOS Intel; torch terkunci di 2.2.2. VPS Ubuntu 24.04
  sebaiknya memakai torch ≥ 2.6. Lihat catatan di `pyproject.toml`.

## Yang sudah diverifikasi di Fase 0

```
import_colab  → 260 FAQ, 70 butuh_verifikasi (26,9%) — cocok dengan dokumen rencana
reindex       → 260 vektor, dim 384, index v1
regression    → Acc@1 0.139 < 0.85 → index DITOLAK (gate bekerja)
cari('apa itu ubb')      → [1] Apa itu Universitas Bangka Belitung? (0.9955)
tier jawaban             → isi dari DB, verbatim
tier sapaan              → 'halo'
tier fallback            → 'resep rendang padang' (0.18, di luar domain)
tier eskalasi            → 'berapa luas kampus' (0.99 tapi butuh_verifikasi)
```

`text.py` sudah diverifikasi **byte-identik** dengan sel 4a notebook.
