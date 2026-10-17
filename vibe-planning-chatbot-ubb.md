# Vibe Planning — Admin Panel & API Chatbot PMB UBB

**Versi** 1.0 · Agustus 2026
**Stack** Django 5.1 + django-ninja + PostgreSQL 16 + Redis + Nginx · Ubuntu 24.04
**Domain** `chatbot-ubb.tech` · **Konsumen API** `https://pmb.ubb.ac.id`
**VPS** 2 vCPU · 8 GB RAM · 100 GB disk · 8 TB bandwidth

---

## 1. Ringkasan

Membangun satu aplikasi Django yang menjalankan dua peran sekaligus:

1. **Admin panel** untuk panitia PMB mengurasi basis pengetahuan chatbot — 260 pertanyaan-jawaban, variasi cara bertanya, dan antrean pertanyaan yang belum terjawab.
2. **API retrieval** yang dipanggil widget chat di `pmb.ubb.ac.id`, memakai model bi-encoder hasil fine-tuning dari notebook Colab.

Keduanya berbagi satu basis kode, satu basis data, dan satu model di memori.

### Kalimat yang menjelaskan seluruh sistem

> Model **tidak menulis jawaban**. Model hanya memutuskan **jawaban mana** dari basis data yang paling cocok. Isi jawabannya dikirim apa adanya seperti yang diketik panitia PMB.

Kalau ada satu kalimat yang harus dipahami setiap orang yang menyentuh proyek ini, itu kalimatnya. Semua keputusan teknis di bawah mengalir dari sana.

---

## 2. Prinsip yang tidak bisa ditawar

Tujuh aturan ini menentukan karakter sistem. Kalau sebuah keputusan teknis bertabrakan dengannya, keputusan itu yang mengalah.

| # | Prinsip | Konsekuensi teknis |
|---|---------|--------------------|
| 1 | **Nol halusinasi** | Jawaban selalu `SELECT` dari tabel `faq`. Tidak ada LLM generatif di jalur runtime. |
| 2 | **Setiap jawaban dapat diaudit** | Response menyertakan `answer_id`, `sumber`, dan `terakhir_diverifikasi`. |
| 3 | **Diam lebih baik daripada salah** | Tiga ambang: jawab / minta kejelasan / arahkan ke petugas. Skor rendah → menolak, bukan menebak. |
| 4 | **Jawaban belum terverifikasi tidak pernah tampil** | Flag `butuh_verifikasi` mengganti jawaban dengan pesan eskalasi, otomatis. |
| 5 | **Menambah FAQ ≠ melatih ulang model** | Reindex adalah operasi hitungan detik, bisa dijalankan admin dari panel. |
| 6 | **Model boleh mati, layanan tidak** | Kegagalan model/Redis → pesan fallback yang sopan, bukan HTTP 500. |
| 7 | **Kualitas dijaga di titik input** | Cek tabrakan sebelum simpan; regression test sebelum index dipasang. |

### Nada bicara chatbot ke camaba

- Bahasa Indonesia baku tapi hangat. Sapa "Anda", bukan "kamu".
- Jangan minta maaf berlebihan. Satu "Maaf" cukup, lalu langsung arahkan.
- Jangan pernah menjanjikan hal yang tidak ada di data ("mungkin sekitar…", "biasanya…").
- Saat tidak tahu, **selalu** beri jalan keluar: tautan atau kontak Panitia PMB.
- Sertakan tanggal verifikasi pada informasi yang berubah tiap tahun (jadwal, biaya).

---

## 3. Peta sistem — satu VPS

```
                    Internet
                       │
        ┌──────────────┴───────────────┐
        │                              │
  pmb.ubb.ac.id                  chatbot-ubb.tech
  (widget JS, di luar            (VPS Anda)
   kendali Anda)                        │
        │                               ▼
        │                     ┌──────────────────────┐
        └────── fetch ───────▶│  Nginx :443 (TLS)    │
                              └───┬──────────┬───────┘
                                  │          │
                    api.chatbot-ubb.tech   admin.chatbot-ubb.tech
                    (publik, rate limit)   (allowlist IP)
                                  │          │
                                  ▼          ▼
                     ┌────────────────┐  ┌──────────────────┐
                     │ gunicorn :8000 │  │ gunicorn :8001   │
                     │ 2 worker       │  │ 1 worker         │
                     │ urls_api.py    │  │ urls_admin.py    │
                     └────────┬───────┘  └────────┬─────────┘
                              │                   │
                              └─────────┬─────────┘
                                        ▼
                        ┌───────────────────────────────┐
                        │ PostgreSQL 16  ·  Redis 7     │
                        └───────────────────────────────┘
```

### Kenapa dua process group

Satu basis kode, dua proses gunicorn. Alasannya:

- **Isolasi beban.** Reindex dan pencarian di admin panel tidak menyita worker yang sedang melayani camaba.
- **Isolasi keamanan.** Proses admin tidak pernah terekspos ke internet publik. Kalaupun ada kerentanan di kode admin, ia tidak terjangkau dari luar.
- **RAM tersedia.** Dengan 8 GB, satu salinan model tambahan (~600 MB) bukan masalah. Kalau hanya 4 GB, saya akan menyarankan satu process group.

### Kenapa dua subdomain

`chatbot-ubb.tech` milik Anda sendiri, jadi subdomain gratis dan instan — tidak perlu menunggu admin DNS UBB. Manfaatkan itu:

| Subdomain | Isi | Akses |
|-----------|-----|-------|
| `api.chatbot-ubb.tech` | Hanya `/v1/*` | Publik, rate limit |
| `admin.chatbot-ubb.tech` | Hanya `/admin/*` + `/static/` | Allowlist IP |

> **Catatan non-teknis yang perlu diantisipasi.** Domain `.tech` terlihat kurang resmi untuk layanan PTN, dan camaba yang teliti akan menyadari widget di `pmb.ubb.ac.id` memanggil domain pihak ketiga. Ini **tidak menghalangi peluncuran**, tapi ajukan `chatbot.ubb.ac.id` ke tim IT UBB secara paralel. Saat A-record-nya jadi, pemindahan hanya soal sertifikat baru dan satu baris `CORS_ORIGINS` — nol perubahan kode.

---

## 4. Anggaran sumber daya

Spesifikasi Anda lapang. Ini penting diketahui supaya tidak ada yang mengoptimasi hal yang salah.

### RAM — 8 GB

| Komponen | Perkiraan |
|----------|-----------|
| gunicorn API (master + 2 worker, `preload_app`) | ~900 MB |
| gunicorn admin (1 worker) | ~600 MB |
| PostgreSQL | ~300 MB |
| Redis (dibatasi `maxmemory 512mb`) | 512 MB |
| OS + Docker | ~500 MB |
| **Terpakai** | **~2,8 GB** |
| **Cadangan** | **~5 GB** |

Kunci penghematan: `preload_app = True`. Model dimuat sekali di proses induk lalu di-fork; di Linux sebagian besar halaman memori dibagi lewat copy-on-write, jadi worker kedua **tidak** menambah 600 MB penuh.

### CPU — 2 core (ini batasan sesungguhnya)

Encoding query bersifat CPU-bound: ~25–40 ms per query dengan `torch.set_num_threads(1)`.

- Kapasitas tanpa cache: **~40–50 request/detik**
- Puncak realistis hari pengumuman SNBP: 10.000 camaba dalam 1 jam ≈ **3 request/detik**

Margin sekitar 15×. Yang menghabiskan CPU justru **reindex** (encode ~1.300 vektor sekaligus, 20–40 detik) — karena itu proses admin dipisah.

> Set `torch_threads=1`. Membiarkan torch memakai kedua core sambil menjalankan 3 proses justru memperlambat karena antar-proses rebutan CPU.

### Disk — 100 GB

| Isi | Perkiraan |
|-----|-----------|
| OS + image Docker | ~8 GB |
| Model + artefak | ~2 GB |
| PostgreSQL (termasuk log 1 tahun) | ~1 GB |
| Snapshot index (2 MB × 50 versi) | ~100 MB |
| Backup harian, retensi 30 hari | ~2 GB |
| **Total** | **< 15 GB** |

Simpan snapshot index sebanyak-banyaknya — ukurannya sepele dan rollback jadi instan.

### Bandwidth — 8 TB

Response rata-rata ~2 KB. Satu juta percakapan ≈ 2 GB. **Tidak akan pernah jadi masalah**; abaikan sepenuhnya dalam perencanaan.

---

## 5. Struktur proyek

```
chatbot_ubb/
├── manage.py
├── pyproject.toml
├── config/
│   ├── settings/
│   │   ├── base.py          # bersama
│   │   ├── dev.py
│   │   └── prod.py          # DEBUG=False, secure cookie, ALLOWED_HOSTS
│   ├── urls_api.py          # hanya /v1/* + /healthz
│   ├── urls_admin.py        # hanya /admin/* + /static/*
│   ├── wsgi_api.py
│   └── wsgi_admin.py
├── faq/                     # domain inti
│   ├── models.py            # Faq · FaqVariasi · IndexVersion
│   ├── admin.py             # ⭐ tempat sebagian besar nilai proyek ini
│   ├── actions.py           # aksi massal: verifikasi, reindex, ekspor
│   └── management/commands/
│       ├── import_colab.py  # artefak notebook → DB
│       ├── reindex.py       # untuk cron
│       └── backup_kb.py
├── retrieval/               # semua urusan model
│   ├── apps.py              # ⚠️ pemuatan model + penjagaannya
│   ├── engine.py            # port dari engine.py FastAPI (versi sinkron)
│   ├── text.py              # ⚠️ HARUS identik dengan notebook
│   ├── indexer.py           # bangun ulang + regression gate
│   └── tiers.py             # keputusan jawab/klarifikasi/eskalasi/fallback
├── api/
│   ├── schemas.py           # Pydantic — dipakai ulang dari proyek FastAPI
│   ├── router.py            # django-ninja
│   └── throttle.py
├── percakapan/              # log & umpan balik
│   ├── models.py            # ChatLog · Feedback
│   └── admin.py             # read-only + antrean konten
├── deploy/
│   ├── nginx/               # dua server block
│   ├── gunicorn_api.py
│   ├── gunicorn_admin.py
│   └── systemd/             # atau docker-compose.yml
└── artifacts/               # model/, knowledge_base.json, config.json, hard_eval.json
```

### Prinsip pemisahan

`retrieval/` **tidak boleh mengimpor apa pun dari `faq/` atau `api/`**. Ia menerima teks, mengembalikan skor. Dengan begitu ia bisa diuji tanpa Django dan tanpa basis data — dan itu satu-satunya cara memastikan logika retrieval Anda benar-benar teruji.

---

## 6. Model data

```python
class Faq(models.Model):
    pertanyaan   = models.TextField()
    jawaban      = models.TextField()
    kategori     = models.CharField(max_length=120, blank=True, db_index=True)
    sumber_label = models.CharField(max_length=200, blank=True)
    sumber_url   = models.URLField(blank=True)

    # Jawaban yang belum disahkan unit terkait. Entri TETAP masuk index agar
    # niat camaba tetap dikenali, tetapi saat runtime jawabannya diganti pesan
    # eskalasi. Inilah yang mencegah placeholder tampil ke publik.
    butuh_verifikasi      = models.BooleanField(default=False, db_index=True)
    terakhir_diverifikasi = models.DateField(null=True, blank=True)
    berlaku_sampai        = models.DateField(null=True, blank=True)

    aktif  = models.BooleanField(default=True, db_index=True)
    dibuat = models.DateTimeField(auto_now_add=True)
    diubah = models.DateTimeField(auto_now=True)


class FaqVariasi(models.Model):
    """Satu jawaban, banyak cara bertanya.

    Tiap baris di sini menjadi satu vektor tambahan yang menunjuk faq yang sama.
    Peningkatan akurasi termurah yang tersedia, dan TIDAK memerlukan pelatihan
    ulang model.
    """
    faq   = models.ForeignKey(Faq, on_delete=models.CASCADE, related_name="variasi")
    teks  = models.TextField()
    asal  = models.CharField(max_length=20, default="admin",
                             choices=[("admin","Ditulis admin"),
                                      ("log","Dari log camaba"),
                                      ("augmentasi","Hasil augmentasi")])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["faq","teks"], name="variasi_unik")]


class IndexVersion(models.Model):
    versi         = models.PositiveIntegerField(unique=True)
    vektor        = models.BinaryField()          # float32 mentah (n, dim)
    pemilik       = models.JSONField()            # [faq_id, ...] sepanjang n
    dim           = models.PositiveSmallIntegerField()
    jumlah_vektor = models.PositiveIntegerField()
    jumlah_answer = models.PositiveIntegerField()
    acc_at_1      = models.FloatField(null=True)  # hasil regression test
    aktif         = models.BooleanField(default=False)
    dibuat        = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["aktif"], condition=Q(aktif=True),
                                    name="satu_index_aktif")
        ]


class ChatLog(models.Model):
    """Aset terbesar sistem ini.

    tipe='fallback'    → pertanyaan yang HILANG dari FAQ  → antrean tambah konten
    tipe='klarifikasi' → intent yang masih AMBIGU         → antrean rapikan data
    Log 3 bulan pertama = data latih nyata untuk fine-tuning putaran kedua.
    """
    log_id = models.CharField(max_length=40, primary_key=True)
    query  = models.TextField()
    tipe   = models.CharField(max_length=16, db_index=True)
    skor   = models.FloatField()
    faq    = models.ForeignKey(Faq, null=True, on_delete=models.SET_NULL)
    session_id, index_version, latency_ms, cached, dibuat = ...


class Feedback(models.Model):
    log_id   = models.OneToOneField(ChatLog, on_delete=models.CASCADE)
    rating   = models.CharField(max_length=4, choices=[("up","👍"),("down","👎")])
    komentar = models.TextField(blank=True)
```

**Catatan:** `vektor` disimpan sebagai `BinaryField` di PostgreSQL, bukan file. Alasannya: rollback dan konsistensi versi dijamin oleh transaksi basis data, dan restart service tidak perlu encode ulang.

---

## 7. Admin panel — di sinilah nilai proyeknya

Django admin bukan sekadar CRUD di sini. Ia adalah **alat kerja panitia PMB**. Rancang halamannya mengikuti pekerjaan mereka, bukan mengikuti tabel.

### 7.1 Halaman FAQ

```python
@admin.register(Faq)
class FaqAdmin(admin.ModelAdmin):
    list_display  = ("pertanyaan_singkat", "kategori", "status_verifikasi",
                     "jumlah_variasi", "terakhir_diverifikasi")
    list_filter   = ("butuh_verifikasi", "kategori", "aktif")
    search_fields = ("pertanyaan", "jawaban", "variasi__teks")
    inlines       = [VariasiInline]
    actions       = ["tandai_terverifikasi", "reindex_sekarang"]
    list_per_page = 50
```

**Yang wajib ada:**

| Elemen | Alasan |
|--------|--------|
| Filter `butuh_verifikasi` | 70 dari 260 jawaban belum final. Filter ini mengubahnya jadi daftar kerja yang bisa dibagi ke unit terkait — ini pekerjaan terpenting sebelum go-live. |
| Inline variasi (min. 3 baris kosong) | Membuat menambah parafrase terasa wajar, bukan fitur tersembunyi. |
| Peringatan tabrakan saat simpan | Lihat 7.2 |
| Kolom `terakhir_diverifikasi` menyala merah bila > 12 bulan | Data PMB kedaluwarsa tiap tahun. |
| Aksi massal "tandai terverifikasi" | Panitia menyetujui 20 jawaban sekaligus, bukan satu per satu. |
| Pratinjau "seperti apa camaba melihatnya" | Menutup jarak antara "saya mengetik jawaban" dan "beginilah tampilnya". |

### 7.2 Cek tabrakan — fitur paling penting di seluruh panel

```python
def save_model(self, request, obj, form, change):
    tabrakan = engine.cari_mirip(obj.pertanyaan, ambang=0.85, abaikan=obj.pk)
    if tabrakan:
        atas = tabrakan[0]
        messages.warning(request, format_html(
            'Sangat mirip dengan <a href="{}">“{}”</a> (kemiripan {:.2f}). '
            'Pertimbangkan menambahkannya sebagai <b>variasi pertanyaan</b> '
            'daripada entri baru.',
            reverse("admin:faq_faq_change", args=[atas.faq_id]),
            atas.pertanyaan, atas.skor))
    super().save_model(request, obj, form, change)
```

**Kenapa ini krusial.** Dua entri yang praktis sama — *"Fakultas Hukum ada?"* dan *"Jurusan Hukum ada?"* — membuat retrieval ambigu **selamanya**. Tidak ada model yang bisa memilih dengan benar di antara keduanya, dan akurasi turun tanpa ada yang tahu penyebabnya. Mencegahnya di titik input jauh lebih murah daripada mendeteksinya tiga bulan kemudian.

Peringatan, **bukan** blokir. Admin mungkin punya alasan sah; beri informasi, jangan halangi.

### 7.3 Halaman antrean konten

Halaman kustom (`ModelAdmin` read-only atau `admin_view`) yang menampilkan pertanyaan camaba yang gagal dijawab:

```
Pertanyaan camaba                        Frekuensi  Skor rata  Terakhir
─────────────────────────────────────────────────────────────────────────
"berapa ukt teknik mesin"                    47      0.61      2 jam lalu   [+ Buat FAQ]
"kapan pengumuman mandiri"                   31      0.58      5 jam lalu   [+ Buat FAQ]
"boleh pindah jurusan gak"                   18      0.42      1 hari lalu  [+ Buat FAQ]
```

Tombol **[+ Buat FAQ]** membuka form tambah dengan `pertanyaan` sudah terisi. Ini menutup lingkaran: camaba bertanya → sistem gagal → admin melihat → konten ditambahkan → camaba berikutnya terjawab.

Halaman ini adalah alasan utama sistem membaik seiring waktu. Jangan tunda ke fase berikutnya.

### 7.4 Halaman index

```
Versi  Vektor  Jawaban  Acc@1   Dibuat            Status
──────────────────────────────────────────────────────────────
  14    1.312     268    0.891  22 Agu 09:14      ● AKTIF
  13    1.298     266    0.884  20 Agu 16:02      [Rollback]
  12    1.290     265    0.877  18 Agu 11:30      [Rollback]

                                        [⟳ Bangun Ulang Index]
```

Tombol reindex menjalankan proses di **thread terpisah** dengan indikator status, bukan memblokir request HTTP selama 40 detik.

### 7.5 Peran pengguna

| Peran | Kewenangan |
|-------|------------|
| **Editor Konten** (staf PMB) | CRUD FAQ & variasi, lihat antrean. Tidak bisa reindex. |
| **Verifikator** (kepala unit) | Semua di atas + menandai `butuh_verifikasi=False`. |
| **Operator** (Anda) | Semua + reindex, rollback, akses log. |

Django `Group` + `Permission` sudah cukup; jangan bangun sistem peran sendiri. `django.contrib.admin.LogEntry` otomatis mencatat siapa mengubah apa — jejak audit yang penting untuk sistem milik PTN.

### 7.6 Tampilan

Django admin fungsional tapi polos. Pasang **`django-unfold`** — tampilan modern dengan konfigurasi minimal, dan panitia PMB yang bukan orang teknis akan jauh lebih nyaman. Sisihkan setengah hari untuk ini; dampaknya pada adopsi besar.

Ubah label agar berbahasa kerja mereka, bukan bahasa tabel:
- "Faq" → **"Pertanyaan & Jawaban"**
- "Butuh verifikasi" → **"Menunggu persetujuan unit"**
- "Faq variasi" → **"Variasi cara bertanya"**

---

## 8. API

Kontrak sudah final di `chatbot-camaba-ubb-api.yaml`. **Bentuk response tidak berubah** — django-ninja menghasilkan JSON yang sama persis dengan versi FastAPI, sehingga frontend yang sudah dibuat tidak perlu disentuh.

```python
# api/router.py
from ninja import NinjaAPI, Router

api = NinjaAPI(title="API Chatbot Camaba UBB", version="1.0.0",
               docs_url=None)   # matikan docs di produksi

chat = Router(tags=["chat"])

@chat.post("/query", response=Envelope[ChatQueryData])
def query(request, payload: ChatQueryRequest):
    ...
```

`api/schemas.py` dipakai **apa adanya** dari proyek FastAPI — itu keuntungan memilih django-ninja daripada DRF.

### Endpoint

| Metode | Path | Auth | Catatan |
|--------|------|------|---------|
| POST | `/v1/chat/query` | — | Rate limit per IP |
| POST | `/v1/chat/feedback` | — | Sinyal untuk fine-tuning berikutnya |
| GET | `/v1/health` | — | 503 saat model belum siap |
| GET | `/healthz` | — | Cek ringan untuk Nginx, tanpa sentuh model |

Endpoint admin **tidak diekspos sebagai API** — semuanya lewat Django admin. Ini menyederhanakan permukaan serangan secara signifikan dibanding rencana FastAPI sebelumnya.

### CORS

```python
CORS_ALLOWED_ORIGINS = [
    "https://pmb.ubb.ac.id",
    "https://www.ubb.ac.id",       # bila widget disematkan di situs utama
]
CORS_ALLOW_CREDENTIALS = False     # tidak perlu cookie; session_id di body
CORS_ALLOW_METHODS = ["GET", "POST", "OPTIONS"]
CORS_PREFLIGHT_MAX_AGE = 3600
```

**Jangan `CORS_ALLOW_ALL_ORIGINS = True`.** Itu berarti situs mana pun boleh memakai API Anda atas biaya VPS Anda.

Karena `pmb.ubb.ac.id` dan `api.chatbot-ubb.tech` beda origin, **semua panggilan lintas-origin** dan preflight `OPTIONS` akan terjadi. `CORS_PREFLIGHT_MAX_AGE` menghemat satu roundtrip per sesi.

### Kenapa endpoint chat tanpa API key

Widget berjalan di browser. Apa pun yang ada di bundle JavaScript bisa dibaca siapa saja lewat DevTools — kunci di sana tidak melindungi apa pun. Perlindungan sesungguhnya:

1. Rate limit per IP di Nginx (20 req/menit) **dan** di aplikasi
2. `CORS_ALLOWED_ORIGINS` yang eksplisit
3. Batas panjang input 500 karakter
4. Endpoint admin di subdomain terpisah dengan allowlist IP

---

## 9. Mesin retrieval

### 9.1 Pemuatan model — hati-hati dengan `AppConfig.ready()`

```python
class RetrievalConfig(AppConfig):
    name = "retrieval"

    def ready(self):
        import sys, os
        # ready() juga dipanggil saat migrate/collectstatic/shell. Memuat model
        # 600 MB hanya untuk menjalankan migrasi itu pemborosan dan memperlambat
        # deploy secara signifikan.
        perintah_tanpa_model = {"migrate", "makemigrations", "collectstatic",
                                "shell", "createsuperuser", "test"}
        if perintah_tanpa_model & set(sys.argv):
            return
        # Hindari pemuatan ganda oleh autoreload dev server
        if os.environ.get("RUN_MAIN") == "false":
            return
        from .engine import muat_engine_global
        muat_engine_global()
```

Ini jebakan nomor satu Django + model ML. Tanpa penjagaan ini, setiap `manage.py migrate` menunggu 15 detik dan memakan 600 MB tanpa alasan.

### 9.2 Sinkron, bukan async

Gunicorn sync worker berarti `model.encode()` yang memblokir hanya menahan **satu worker**, bukan membekukan event loop. Seluruh kerumitan `anyio.to_thread` dan `CapacityLimiter` dari versi FastAPI **lenyap**. Ini penyederhanaan nyata, bukan kompromi.

```python
# gunicorn_api.py
bind = "127.0.0.1:8000"
workers = 2
worker_class = "sync"
preload_app = True          # satu model, dibagi antar-worker lewat copy-on-write
timeout = 60
graceful_timeout = 30
max_requests = 2000         # daur ulang worker: lawan kebocoran memori bertahap
max_requests_jitter = 200   # jangan sampai semua worker restart bersamaan
```

`max_requests` penting untuk layanan yang hidup berbulan-bulan. Proses Python yang memegang tensor cenderung merambat naik pemakaian memorinya.

### 9.3 Index sebagai snapshot immutable

Reindex **tidak pernah** mengubah index yang sedang dipakai. Ia membangun objek baru, mengujinya, lalu menukar satu referensi modul. Request yang sedang berjalan tetap memakai snapshot lamanya sampai selesai — tanpa penguncian, tanpa kemungkinan ada yang membaca index setengah jadi.

**Peringatan multi-proses:** dengan 3 worker, reindex dari proses admin **tidak** otomatis terlihat oleh worker API. Solusi paling sederhana dan cukup andal: setiap worker memeriksa `IndexVersion.objects.filter(aktif=True).values_list("versi")` setiap N detik (query sangat murah), dan memuat ulang bila berbeda. Redis pub/sub adalah alternatif yang lebih rapi bila nanti diperlukan — jangan bangun di awal.

### 9.4 Regression gate

Sebelum index kandidat dipasang, uji terhadap `hard_eval.json`:

```
Acc@1 ≥ 0.85  →  pasang, naikkan versi
Acc@1 <  0.85  →  TOLAK, versi lama tetap melayani, tampilkan entri penyebab
```

Inilah yang menangkap kasus admin tanpa sadar menambahkan pertanyaan yang bertabrakan. Kalau `hard_eval.json` tidak ada, uji dilewati — **tampilkan status ini dengan jelas di halaman index**, jangan sampai admin mengira terlindungi padahal belum.

### 9.5 ⚠️ `retrieval/text.py` harus identik dengan notebook

Normalisasi saat membangun index wajib sama persis dengan saat runtime. Beda satu karakter membuat vektor query dan vektor dokumen berada di ruang yang sedikit berbeda — **akurasi turun tanpa satu pun error muncul**. Jenis bug yang paling sulit dilacak.

Tulis satu unit test yang menjadi pagarnya:

```python
def test_normalisasi_sesuai_notebook():
    kasus = json.load(open("artifacts/normalisasi_gold.json"))
    for masukan, harapan in kasus:
        assert normalize(masukan) == harapan
```

Hasilkan `normalisasi_gold.json` dari notebook. Kalau tes ini merah, **jangan deploy**.

---

## 10. Deployment — Ubuntu 24.04

Ubuntu 24.04 sudah membawa Python 3.12, cocok dengan target proyek.

### 10.1 Penguatan server (sebelum apa pun)

```bash
# Pengguna non-root
adduser deploy && usermod -aG sudo deploy

# SSH: kunci saja, tanpa password
# /etc/ssh/sshd_config → PermitRootLogin no · PasswordAuthentication no
systemctl restart ssh

# Firewall
ufw default deny incoming && ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable

# Pembaruan keamanan otomatis
apt install unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades

# Perlindungan brute-force
apt install fail2ban && systemctl enable --now fail2ban
```

### 10.2 DNS

| Record | Nilai |
|--------|-------|
| `A` `api.chatbot-ubb.tech` | IP VPS |
| `A` `admin.chatbot-ubb.tech` | IP VPS |

Karena domainnya milik Anda, ini selesai dalam hitungan menit — tidak perlu menunggu siapa pun.

### 10.3 TLS

```bash
snap install --classic certbot
certbot --nginx -d api.chatbot-ubb.tech -d admin.chatbot-ubb.tech
systemctl list-timers | grep certbot   # pastikan perpanjangan otomatis aktif
```

**Wajib HTTPS.** `pmb.ubb.ac.id` disajikan lewat HTTPS, dan browser memblokir **total** panggilan HTTP dari halaman HTTPS (*mixed content*) — tidak bisa di-bypass.

### 10.4 Nginx

```nginx
limit_req_zone $binary_remote_addr zone=chat:10m rate=20r/m;

# ── API publik ────────────────────────────────────────────
server {
    listen 443 ssl http2;
    server_name api.chatbot-ubb.tech;

    client_max_body_size 16k;          # query maksimal 500 karakter
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    location /v1/ {
        limit_req zone=chat burst=10 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8000;
        # Tanpa header ini semua request terlihat dari 127.0.0.1 dan rate limit
        # aplikasi akan memblokir SELURUH pengguna sekaligus.
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Host $host;
        proxy_read_timeout 15s;
    }
    location /healthz { access_log off; proxy_pass http://127.0.0.1:8000; }
    location / { return 404; }
}

# ── Admin ─────────────────────────────────────────────────
server {
    listen 443 ssl http2;
    server_name admin.chatbot-ubb.tech;

    allow 203.0.113.45;        # IP kantor Diskominfo
    deny all;

    location /static/ { alias /srv/static/; expires 30d; }
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Host $host;
        proxy_read_timeout 180s;   # reindex butuh waktu
    }
}
```

> **Rencanakan sejak awal** kalau panitia PMB perlu mengakses admin dari luar kantor. Allowlist IP tidak praktis untuk mereka. Alternatif: WireGuard VPN (paling aman), atau hapus allowlist dan andalkan login Django + `django-axes` + 2FA. Putuskan ini **sebelum** menyerahkan panel ke mereka, bukan sesudah.

### 10.5 Django settings produksi

```python
DEBUG = False
ALLOWED_HOSTS = ["api.chatbot-ubb.tech", "admin.chatbot-ubb.tech"]
CSRF_TRUSTED_ORIGINS = ["https://admin.chatbot-ubb.tech"]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]   # KeyError kalau lupa — itu disengaja
```

`SECURE_PROXY_SSL_HEADER` sering terlupa. Tanpa itu Django mengira koneksinya HTTP dan menolak menetapkan secure cookie — login admin gagal dengan pesan yang membingungkan.

### 10.6 Urutan deploy

```bash
git pull
python manage.py migrate --noinput
python manage.py collectstatic --noinput
systemctl reload gunicorn-api      # reload, bukan restart: tanpa putus layanan
systemctl restart gunicorn-admin
```

`systemctl reload` pada gunicorn memulai worker baru sebelum mematikan yang lama, jadi camaba tidak melihat error. Restart penuh hanya perlu bila model atau `preload_app` berubah.

---

## 11. Operasional

### 11.1 Backup — bagian paling penting di bagian ini

Basis pengetahuan Anda adalah hasil kerja berbulan-bulan mengurasi 260 FAQ. Satu VPS berarti tidak ada redundansi.

```bash
# /etc/cron.d/backup-chatbot
0 2 * * * deploy pg_dump -U ubb chatbot | gzip > /backup/kb-$(date +\%F).sql.gz
30 2 * * * deploy rclone copy /backup/ gdrive:backup-chatbot/ --max-age 2d
0 3 * * 0 deploy find /backup -name '*.sql.gz' -mtime +30 -delete
```

**Salin keluar dari VPS.** Backup yang tersimpan di server yang sama dengan datanya bukan backup. Google Drive kampus atau cPanel yang sudah Anda punya sama-sama bisa dipakai.

Tambahkan aksi **"Ekspor ke Excel"** di admin FAQ. Panitia PMB akan merasa lebih tenang bila bisa mengunduh salinan sendiri — dan itu lapis pemulihan tambahan yang gratis.

**Uji restore setiap kuartal.** Backup yang belum pernah diuji restore statusnya belum diketahui.

### 11.2 Terjadwal

| Tugas | Frekuensi | Perintah |
|-------|-----------|----------|
| Backup DB | harian 02:00 | `pg_dump` |
| Kirim backup keluar | harian 02:30 | `rclone` |
| Bersihkan `ChatLog` > 12 bulan | bulanan | `manage.py bersihkan_log` |
| Ingatkan FAQ kedaluwarsa | mingguan | email FAQ dengan `terakhir_diverifikasi` > 12 bulan |
| Perpanjang TLS | otomatis | timer certbot |

### 11.3 Monitoring

Jangan bangun Grafana. Untuk skala ini cukup:

- **UptimeRobot** (gratis) memantau `https://api.chatbot-ubb.tech/healthz` tiap 5 menit
- **Sentry** (tier gratis) untuk exception — jauh lebih berguna daripada membaca log manual
- **Halaman statistik** di admin: jumlah query per hari, sebaran tipe, rasio 👍/👎, latensi p95

Yang benar-benar perlu diawasi: **rasio `fallback`**. Kalau naik tiba-tiba, ada yang salah — bisa kesalahan reindex, bisa musim bertanya baru yang belum tercakup FAQ.

### 11.4 Runbook singkat

| Gejala | Langkah pertama |
|--------|-----------------|
| Chatbot menjawab ngawur setelah update | Cek `index_version` di response → rollback ke versi sebelumnya |
| Semua request 429 | Cek `X-Forwarded-For` diteruskan Nginx |
| Login admin gagal, tanpa pesan jelas | Cek `SECURE_PROXY_SSL_HEADER` dan `CSRF_TRUSTED_ORIGINS` |
| Widget di `pmb.ubb.ac.id` tidak merespons | Buka DevTools → cek error CORS atau mixed content |
| RAM merambat naik | Turunkan `max_requests`; cek kebocoran di kode kustom |
| Reindex menggantung | Cek log gunicorn admin; naikkan `proxy_read_timeout` |

---

## 12. Roadmap bertahap

Setiap fase harus **bisa dideploy dan berguna**. Jangan gabungkan.

### Fase 0 — Fondasi (2–3 hari)
Proyek Django, models + migrasi, `import_colab`, `retrieval/` yang lolos unit test.
**Selesai bila:** `python manage.py shell` bisa memanggil `engine.cari("apa itu ubb")` dan hasilnya benar.

### Fase 1 — Admin panel (3–4 hari) ⭐ prioritas tertinggi
FaqAdmin lengkap + inline variasi + cek tabrakan + peran pengguna + django-unfold.
**Selesai bila:** panitia PMB bisa login dan menuntaskan satu jawaban "Perlu wawancara" tanpa dibimbing.

> Fase ini **mendahului** API dengan sengaja. Penyumbat sesungguhnya bukan kode, melainkan 70 jawaban yang belum terverifikasi. Semakin cepat panel siap, semakin cepat pekerjaan itu bisa berjalan paralel dengan pengembangan.

### Fase 2 — API (2–3 hari)
Router ninja, empat tier, CORS, rate limit, log percakapan, health check.
**Selesai bila:** `curl` ke endpoint mengembalikan keempat tipe dengan benar, termasuk `fallback` untuk pertanyaan di luar domain.

### Fase 3 — Reindex & regression gate (2 hari)
Halaman index, tombol reindex, rollback, regression gate, deteksi versi antar-worker.
**Selesai bila:** menambah FAQ dari admin → reindex → pertanyaan baru terjawab, tanpa restart.

### Fase 4 — Produksi (2–3 hari)
Nginx, TLS, systemd/Docker, backup, monitoring, uji beban.
**Selesai bila:** widget di halaman uji `pmb.ubb.ac.id` berfungsi, backup terverifikasi bisa di-restore.

### Fase 5 — Penyempurnaan (berkelanjutan)
Antrean konten, dashboard statistik, ekspor Excel, pengingat FAQ kedaluwarsa.

---

## 13. Yang sengaja TIDAK dibangun

Menuliskan ini sama pentingnya dengan menuliskan yang dibangun.

| Tidak dibangun | Alasan |
|----------------|--------|
| Vector database (Qdrant/Pinecone) | 1.300 vektor = satu perkalian matriks NumPy, < 1 ms. Ambang wajarnya 50.000+. |
| LangChain / LlamaIndex | Abstraksi tebal di atas ~50 baris kode, dengan API yang berubah cepat. |
| Kubernetes / autoscaling | Satu VPS dengan margin 15×. |
| LLM generatif di runtime | Melanggar prinsip #1. |
| SPA admin kustom (React) | Django admin sudah memberi 90% kebutuhan secara gratis. |
| Autentikasi untuk endpoint chat | Camaba anonim; kunci di browser tidak melindungi apa pun. |
| WebSocket / streaming | Response < 100 ms. Streaming tidak menambah apa pun. |
| Dukungan multi-bahasa | Camaba UBB berbahasa Indonesia. Tambahkan bila ada permintaan nyata. |
| Blue-green deployment | Deploy jam 2 pagi menyelesaikan masalah yang sama. |

Kalau ada yang mengusulkan salah satu di atas, tanyakan masalah spesifik apa yang sedang dipecahkan. Biasanya tidak ada.

---

## 14. Checklist go-live

**Data**
- [ ] Semua jawaban `butuh_verifikasi` sudah final atau sengaja dibiarkan → tersalurkan ke eskalasi
- [ ] Entri kembar sudah digabung (cek tabrakan tidak lagi memunculkan peringatan pada data lama)
- [ ] Setiap FAQ punya minimal 3 variasi pertanyaan
- [ ] `terakhir_diverifikasi` terisi untuk semua entri jadwal dan biaya

**Kualitas**
- [ ] Acc@1 ≥ 0,85 pada hard eval set
- [ ] Nol query di luar domain lolos di atas `τ_high` (uji dengan ≥ 100 query)
- [ ] Tes normalisasi hijau
- [ ] UAT bersama panitia PMB memakai pertanyaan camaba tahun lalu

**Teknis**
- [ ] HTTPS aktif di kedua subdomain, perpanjangan otomatis terverifikasi
- [ ] CORS hanya mengizinkan `pmb.ubb.ac.id`
- [ ] Rate limit terbukti bekerja (uji dengan `ab` atau `hey`)
- [ ] `DEBUG=False`, `SECRET_KEY` dari environment
- [ ] Backup berjalan **dan** sudah pernah diuji restore
- [ ] Sentry & UptimeRobot menerima data

**Operasional**
- [ ] Panitia PMB sudah dilatih memakai panel
- [ ] Akses admin dari luar kantor sudah diputuskan (VPN atau login + 2FA)
- [ ] Nomor kontak eskalasi benar dan aktif
- [ ] Disclaimer tampil: *"Informasi bersifat indikatif; keputusan resmi mengacu pengumuman UBB."*
- [ ] Runbook tersimpan di tempat yang bisa diakses orang lain, bukan hanya di kepala Anda

---

## 15. Risiko

| Risiko | Dampak | Mitigasi |
|--------|--------|----------|
| 70 jawaban tak kunjung diverifikasi | 1 dari 4 percakapan berujung eskalasi; chatbot terlihat rusak | Fase 1 didahulukan; sediakan daftar kerja terfilter per unit |
| Satu VPS, tidak ada redundansi | Kehilangan basis pengetahuan | Backup harian ke luar VPS + uji restore kuartalan |
| Domain `.tech` terasa kurang resmi | Keraguan camaba, pertanyaan dari pimpinan | Ajukan `chatbot.ubb.ac.id` paralel; pemindahan nol perubahan kode |
| Panitia tidak bisa akses admin dari luar kantor | Panel tidak terpakai | Putuskan VPN vs 2FA **sebelum** serah terima |
| Data PMB berubah tiap tahun | Jawaban basi tampil sebagai fakta | `terakhir_diverifikasi` + pengingat mingguan otomatis |
| Reindex saat jam sibuk | Latensi naik | Proses admin terpisah; imbau reindex malam hari |
| Pergantian personel | Sistem tidak terawat | Runbook tertulis + README + akses tidak terpusat pada satu orang |

---

## 16. Catatan untuk AI coding assistant

Bila dokumen ini diserahkan ke Claude Code atau sejenisnya, sertakan instruksi berikut:

1. **Kerjakan per fase.** Selesaikan dan pastikan bisa dijalankan sebelum lanjut. Jangan menghasilkan seluruh proyek sekaligus.
2. **`retrieval/` tidak boleh mengimpor `faq/` atau `api/`.** Ia harus bisa diuji tanpa Django.
3. **Salin `text.py` apa adanya** dari notebook. Jangan "rapikan" atau "perbaiki" — perbedaan sekecil apa pun merusak akurasi secara diam-diam.
4. **Tulis test dulu** untuk `retrieval/` dan logika tier. Bagian lain boleh menyusul.
5. **Jangan tambahkan dependensi** di luar yang tercantum tanpa alasan yang bisa dijelaskan.
6. **Komentar menjelaskan MENGAPA, bukan APA.** `# encode di sini agar tidak memblokir` berguna; `# encode teks` tidak.
7. Bila sebuah keputusan bertabrakan dengan **Bagian 2**, prinsip yang menang.

---

## Lampiran — dari notebook ke produksi

| Artefak Colab | Tujuan |
|---------------|--------|
| `model/` | `artifacts/model/`, dimuat `RetrievalConfig.ready()` |
| `knowledge_base.json` | Diimpor `manage.py import_colab` → tabel `Faq` |
| `config.json` (`tau_high`, `tau_low`) | Dibaca saat startup; environment bisa menimpa |
| `hard_eval.json` | Regression gate sebelum index dipasang |
| `error_analysis.csv` | Daftar kerja perbaikan konten di admin |

**Yang tidak berpindah:** kode training. Fine-tuning tetap di Colab, dijalankan sekali per musim PMB memakai log produksi sebagai data latih. VPS hanya melakukan inferensi.
