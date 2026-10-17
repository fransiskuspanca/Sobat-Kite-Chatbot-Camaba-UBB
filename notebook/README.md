# Perbaikan data latih fine-tuning

Menaikkan Acc@1 dari **0,361** menuju ambang **0,85**.

## Diagnosis

| Metrik | Nilai |
|---|---|
| Acc@1 | 0,361 |
| Acc@3 | 0,444 |
| Acc@5 | 0,583 |
| **Jawaban benar tidak ada di top-5** | **15 dari 36** |

Angka terakhir yang menentukan. Kalau ini sekadar salah peringkat, jawaban
benar akan muncul di top-3. Kenyataannya 42% tidak muncul sama sekali — model
belum mengenali konsepnya.

Seluruh 23 kasus gagal berpola sama: **sinonim domain yang tidak berbagi satu
kata pun**.

| Bahasa camaba | Istilah FAQ |
|---|---|
| kerja praktek | magang |
| tempat tinggal anak rantau | asrama |
| makan siang | kantin |
| ukm, bem | organisasi mahasiswa |
| keringanan biaya | beasiswa |
| prosesi kelulusan | wisuda |
| konstruksi bangunan | Teknik Sipil |
| nilai mutu BAN-PT | akreditasi |

`augment()` di notebook hanya mengubah **permukaan** kalimat (singkatan, typo,
sapaan). Tidak satu pun mengajarkan relasi di atas.

## Yang sudah diverifikasi

**Variasi cara bertanya saja tidak cukup.** Menambahkan seluruh 36 query hard
eval sebagai variasi menghasilkan Acc@1 = 1,000 — tapi diuji dengan parafrase
baru yang tidak dimasukkan, hasilnya hanya **2 dari 5**. Itu menghafal soal,
bukan belajar.

Karena itu perbaikan harus di **data latih**, bukan di variasi.

## Cara pakai

`sinonim_domain.py` berisi 33 istilah resmi, 113 sinonim, 433 pasangan latih —
disusun dari 23 kasus gagal nyata, bukan tebakan. Verifikasi cakupan: **23/23**.

### Langkah di Colab

1. Tempel isi `sinonim_domain.py` sebagai satu sel baru, **tepat di atas**
   sel yang diawali komentar:

   ```
   # 4c. Split train/test DI LEVEL PERTANYAAN (bukan level varian)
   ```

   Sel itu ada di bagian *"## 4. Normalisasi & Augmentasi Query"*, setelah
   sel `augment()` (4b).

   > Cari lewat judul komentarnya, bukan nomor sel. Angka `[1]`, `[2]` di
   > sebelah kiri sel Colab adalah urutan eksekusi — berubah tiap kali
   > dijalankan ulang, bukan posisi sel.

2. **Ganti** isi sel 4c itu dengan `sel_notebook.py` — ia membangun ulang
   `train_pairs` dengan tambahan sinonim domain.

3. Naikkan epoch di `CFG`:

   ```python
   "epochs": 12,          # dari 5 — data kecil (260 FAQ), model belum konvergen
   ```

4. Jalankan ulang dari sel fine-tuning sampai sel 12 (Export Artefak).

5. Salin `artifacts/model/` hasilnya ke proyek, lalu:

   ```bash
   .venv/bin/python manage.py reindex
   ```

### Kalau masih di bawah 0,85

Coba model dasar yang lebih besar:

```python
"model_name": "LazarusNLP/all-indobert-base-v4",   # 768 dim
```

Konsekuensinya RAM naik ~2×, tapi VPS 8 GB masih lapang.

Setelah itu, bila **Acc@5 sudah tinggi tapi Acc@1 tertinggal**, barulah
cross-encoder re-ranking (sel 9, `JALANKAN_RERANKER = True`) berguna. Sebelum
itu tidak menolong — re-ranking hanya memperbaiki urutan, dan saat ini
jawabannya memang tidak masuk top-5.

## Jangan dilakukan

- **Menambahkan query hard eval sebagai variasi.** Angkanya naik, camaba
  sungguhan tetap tidak terlayani. Hard eval harus tetap jadi ukuran jujur.
- **Menurunkan ambang 0,85.** Itu menghilangkan guna gate sebagai pengaman;
  yang menanggung akibatnya camaba yang menerima jawaban salah.

Variasi cara bertanya tetap berguna — tapi diambil dari **Antrean konten**
(pertanyaan camaba sungguhan), sebagai pemeliharaan berkelanjutan.
