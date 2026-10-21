# Paket data tambahan

Hasil simulasi pertanyaan camaba. Server menjalankan `manage.py sinkron_data`
tiap 15 menit (lihat `deploy/cron-chatbot`): paket yang tercantum di
`daftar.json` dan belum pernah diterapkan akan diimpor, lalu reindex dengan
regression gate biasa. Bentuk paket dijelaskan di `faq/sinkron.py`.
Paket yang membuat regression gate gagal dibatalkan otomatis. Riwayatnya
terlihat di admin: menu **Laporan data simulasi**.

- Paket hanya menambah. Jawaban FAQ yang sudah ada tidak pernah ditimpa.
- Paket yang sudah diterapkan tidak diterapkan lagi; untuk koreksi, buat paket baru.
- Saat membuat versi Excel FAQ berikutnya, masukkan isi semua paket ke Excel,
  karena `import_colab --hapus-dulu` menghapus FAQ yang tidak ada di Excel.
  (Variasi asal log/augmentasi dipulihkan otomatis selama FAQ-nya masih ada.)
