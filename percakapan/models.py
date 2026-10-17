"""Log & umpan balik — lihat Bagian 6 dokumen rencana."""

import uuid

from django.db import models

from faq.models import Faq


def buat_session_id() -> str:
    """ID sesi acak 32 heksadesimal.

    Dibuat di SERVER, bukan diterima dari klien: kalau frontend yang memilih,
    siapa pun bisa menebak/menyalin session_id orang lain dan membaca riwayat
    pertanyaannya. Ini bukan token autentikasi, tapi cukup untuk mencegah
    tabrakan dan pengintipan iseng.
    """
    return uuid.uuid4().hex


class Sesi(models.Model):
    """Identitas camaba untuk satu sesi percakapan.

    Camaba mengisi nama lengkap + jenis kelamin SEBELUM boleh bertanya, lalu
    frontend menyimpan session_id-nya di localStorage. Selama session_id itu
    dipakai, seluruh riwayat pertanyaan tetap terkumpul dalam satu sesi.
    """

    LAKI = "L"
    PEREMPUAN = "P"
    PILIHAN_JENIS_KELAMIN = [(LAKI, "Laki-laki"), (PEREMPUAN, "Perempuan")]

    session_id = models.CharField(max_length=64, primary_key=True,
                                  default=buat_session_id, editable=False)
    nama_lengkap = models.CharField(max_length=120)
    jenis_kelamin = models.CharField(max_length=1,
                                     choices=PILIHAN_JENIS_KELAMIN)
    # Opsional: camaba boleh bertanya tanpa meninggalkan email. Diisi hanya
    # kalau yang bersangkutan sendiri yang mengetiknya di form profil.
    email = models.EmailField(max_length=254, blank=True, db_index=True)
    dibuat = models.DateTimeField(auto_now_add=True, db_index=True)
    # Dipakai untuk kedaluwarsa sesi lama & melihat sesi mana yang masih aktif.
    terakhir_aktif = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name = "Calon camaba"
        verbose_name_plural = "Calon Camaba"
        ordering = ["-terakhir_aktif"]

    def __str__(self):
        return f"{self.nama_lengkap} ({self.get_jenis_kelamin_display()})"

    @property
    def sapaan(self) -> str:
        """Sapaan yang dipakai chatbot saat menyambut camaba.

        Hanya kata sapaannya yang mengikuti jenis kelamin; ISI jawaban tidak
        pernah berbeda antar-camaba.
        """
        return "Bang" if self.jenis_kelamin == self.LAKI else "Kak"


class ChatLog(models.Model):
    """Aset terbesar sistem ini.

    tipe='fallback'    -> pertanyaan yang HILANG dari FAQ  -> antrean tambah konten
    tipe='klarifikasi' -> intent yang masih AMBIGU         -> antrean rapikan data
    Log 3 bulan pertama = data latih nyata untuk fine-tuning putaran kedua.
    """
    log_id = models.CharField(max_length=40, primary_key=True)
    query = models.TextField()
    tipe = models.CharField(max_length=16, db_index=True)
    skor = models.FloatField()
    faq = models.ForeignKey(Faq, null=True, blank=True, on_delete=models.SET_NULL)
    # session_id tetap CharField (bukan hanya FK) supaya log lama tanpa sesi
    # dan log dari sesi yang sudah dihapus tetap terbaca apa adanya.
    session_id = models.CharField(max_length=64, blank=True, db_index=True)
    sesi = models.ForeignKey(Sesi, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="log")
    # Jawaban yang benar-benar dikirim ke camaba — riwayat harus bisa
    # ditampilkan ulang tanpa menjalankan retrieval lagi.
    jawaban = models.TextField(blank=True)
    index_version = models.PositiveIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    cached = models.BooleanField(default=False)
    dibuat = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Log percakapan"
        verbose_name_plural = "Log percakapan"
        ordering = ["-dibuat"]
        indexes = [
            # Riwayat selalu diambil per-sesi terurut waktu.
            models.Index(fields=["session_id", "dibuat"],
                         name="idx_chatlog_sesi_waktu"),
        ]

    def __str__(self):
        return f"[{self.tipe}] {self.query[:60]}"


class Feedback(models.Model):
    log = models.OneToOneField(ChatLog, on_delete=models.CASCADE,
                               related_name="feedback")
    rating = models.CharField(max_length=4, choices=[("up", "👍"), ("down", "👎")])
    komentar = models.TextField(blank=True)
    dibuat = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Umpan balik"
        verbose_name_plural = "Umpan balik"

    def __str__(self):
        return f"{self.rating} — {self.log_id}"
