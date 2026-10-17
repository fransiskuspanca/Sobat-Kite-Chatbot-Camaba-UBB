"""Model domain — lihat Bagian 6 dokumen rencana."""

from django.db import models
from django.db.models import Q


class Faq(models.Model):
    pertanyaan = models.TextField("Pertanyaan")
    jawaban = models.TextField("Jawaban")
    kategori = models.CharField("Kategori", max_length=120, blank=True, db_index=True)
    sub_kategori = models.CharField("Sub-kategori", max_length=120, blank=True)
    sumber_label = models.CharField("Label sumber", max_length=200, blank=True)
    sumber_url = models.URLField("URL sumber", blank=True)

    # Jawaban yang belum disahkan unit terkait. Entri TETAP masuk index agar
    # niat camaba tetap dikenali, tetapi saat runtime jawabannya diganti pesan
    # eskalasi. Inilah yang mencegah placeholder tampil ke publik.
    butuh_verifikasi = models.BooleanField(
        "Menunggu persetujuan unit", default=False, db_index=True)
    terakhir_diverifikasi = models.DateField(
        "Terakhir diverifikasi", null=True, blank=True)
    berlaku_sampai = models.DateField("Berlaku sampai", null=True, blank=True)

    aktif = models.BooleanField("Aktif", default=True, db_index=True)
    dibuat = models.DateTimeField(auto_now_add=True)
    diubah = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pertanyaan & Jawaban"
        verbose_name_plural = "Pertanyaan & Jawaban"
        ordering = ["kategori", "id"]
        permissions = [
            # Menyetujui jawaban adalah kewenangan kepala unit, bukan editor.
            ("dapat_verifikasi", "Dapat menyetujui jawaban (Verifikator)"),
            ("dapat_reindex", "Dapat membangun ulang index (Operator)"),
        ]

    def __str__(self):
        return self.pertanyaan[:80]

    @property
    def sumber(self) -> str:
        """Sumber yang ditampilkan ke camaba. URL diprioritaskan."""
        return self.sumber_url or self.sumber_label


class FaqVariasi(models.Model):
    """Satu jawaban, banyak cara bertanya.

    Tiap baris di sini menjadi satu vektor tambahan yang menunjuk faq yang sama.
    Peningkatan akurasi termurah yang tersedia, dan TIDAK memerlukan pelatihan
    ulang model.
    """
    faq = models.ForeignKey(Faq, on_delete=models.CASCADE, related_name="variasi")
    teks = models.TextField("Teks variasi")
    asal = models.CharField(max_length=20, default="admin",
                            choices=[("admin", "Ditulis admin"),
                                     ("log", "Dari log camaba"),
                                     ("augmentasi", "Hasil augmentasi")])
    dibuat = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Variasi cara bertanya"
        verbose_name_plural = "Variasi cara bertanya"
        constraints = [
            models.UniqueConstraint(fields=["faq", "teks"], name="variasi_unik")
        ]

    def __str__(self):
        return self.teks[:80]


class IndexVersion(models.Model):
    versi = models.PositiveIntegerField(unique=True)
    # Disimpan di basis data, bukan file: rollback dan konsistensi versi
    # dijamin transaksi, dan restart service tidak perlu encode ulang.
    vektor = models.BinaryField()                 # float32 mentah (n, dim)
    pemilik = models.JSONField()                  # [faq_id, ...] sepanjang n
    dim = models.PositiveSmallIntegerField()
    jumlah_vektor = models.PositiveIntegerField()
    jumlah_answer = models.PositiveIntegerField()
    acc_at_1 = models.FloatField(null=True, blank=True)   # hasil regression test
    catatan = models.TextField(blank=True)
    aktif = models.BooleanField(default=False)
    dibuat = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Versi index"
        verbose_name_plural = "Versi index"
        ordering = ["-versi"]
        constraints = [
            models.UniqueConstraint(fields=["aktif"], condition=Q(aktif=True),
                                    name="satu_index_aktif")
        ]

    def __str__(self):
        return f"v{self.versi} ({self.jumlah_vektor} vektor)"


class PengaturanSapaan(models.Model):
    """Kata pengantar pembuka chatbot — SATU baris saja (singleton).

    Kalimat sambutan sering diubah tiap musim PMB ("gelombang 2 dibuka",
    "pendaftaran ditutup 30 Juni"). Tanpa ini panitia harus minta developer
    menyunting kode; dengan ini cukup satu form di admin.

    Bukan tabel berisi banyak baris: yang dipakai chatbot selalu tepat satu.
    Karena itu pk dikunci ke 1 (lihat save()) dan admin memaksa semua jalan
    masuk menuju baris yang sama.
    """

    # pk dikunci supaya tidak mungkin ada baris kedua, sekalipun ada yang
    # memanggil objects.create() langsung dari shell.
    ID_TUNGGAL = 1

    salam = models.CharField(
        "Kata sapaan", max_length=40, default="Halo",
        help_text="Kata pembuka sebelum nama camaba. Contoh: Halo, Hai, "
                  "Selamat datang.")
    kalimat = models.TextField(
        "Kalimat ajakan", default="silakan bertanya seputar penerimaan "
                                  "mahasiswa baru UBB.",
        help_text="Lanjutan kalimat setelah nama camaba.")

    # Sapaan gender ("Bang"/"Kak") boleh dimatikan — sebagian panitia lebih
    # suka sambutan netral.
    pakai_sapaan_gender = models.BooleanField(
        "Sertakan sapaan Bang/Kak", default=True,
        help_text="Kalau dimatikan, chatbot menyapa dengan nama saja.")

    # --- identitas chatbot ---
    # Dipakai saat camaba bertanya "siapa kamu?". Tanpa ini pertanyaan seperti
    # itu jatuh ke fallback dan chatbot terkesan tidak mengenali dirinya.
    nama_bot = models.CharField(
        "Nama chatbot", max_length=60, default="SOBAT KITE",
        help_text="Nama yang disebut chatbot saat memperkenalkan diri.")
    peran_bot = models.CharField(
        "Peran chatbot", max_length=160,
        default="Asisten Virtual PMB Universitas Bangka Belitung",
        help_text="Keterangan singkat setelah nama.")
    perkenalan = models.TextField(
        "Kalimat perkenalan",
        default="Saya siap membantu Anda dengan informasi seputar penerimaan "
                "mahasiswa baru UBB — jalur masuk, biaya kuliah, program "
                "studi, beasiswa, dan fasilitas kampus.\n\nAda yang ingin "
                "Anda tanyakan?",
        help_text="Lanjutan setelah nama & peran. Boleh beberapa baris.")

    # --- jawaban di luar konteks ---
    # Fallback generik ("saya belum memahami pertanyaan Anda") terasa seperti
    # chatbot rusak. Menyebut ulang apa yang ditanyakan membuat camaba paham
    # bahwa pertanyaannya DITERIMA, hanya di luar cakupan.
    fallback_template = models.TextField(
        "Jawaban di luar konteks", blank=True,
        default="Maaf, saya tidak dapat memberikan informasi tentang "
                "{kunci}. Saya dapat menjawab informasi seputar penerimaan "
                "mahasiswa baru UBB — jalur masuk, biaya kuliah, program "
                "studi, beasiswa, dan fasilitas kampus.",
        help_text="Wajib memuat {kunci} — diganti dengan inti pertanyaan "
                  "camaba. Contoh: camaba mengetik \"siapa prabowo "
                  "subianto?\", {kunci} menjadi \"prabowo subianto\". "
                  "Kosongkan untuk memakai jawaban bawaan.")
    fallback_tanpa_kunci = models.TextField(
        "Jawaban di luar konteks (tanpa kata kunci)", blank=True,
        default="Maaf, saya belum memahami pertanyaan Anda. Saya dapat "
                "menjawab informasi seputar penerimaan mahasiswa baru UBB — "
                "jalur masuk, biaya kuliah, program studi, beasiswa, dan "
                "fasilitas kampus.",
        help_text="Dipakai saat pertanyaan tidak menyisakan kata kunci untuk "
                  "disebut ulang — misalnya camaba hanya mengetik \"???\". "
                  "TIDAK boleh memuat {kunci}.")

    diubah = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kata pengantar pembuka"
        verbose_name_plural = "Kata pengantar pembuka"

    def __str__(self):
        return "Kata pengantar pembuka"

    def save(self, *args, **kwargs):
        # Apa pun yang diminta pemanggil, baris ini selalu baris ke-1.
        self.pk = self.ID_TUNGGAL
        # objects.create() memaksa INSERT; tanpa ini pemanggilan kedua kena
        # UNIQUE constraint, bukan menimpa baris yang sudah ada.
        kwargs.pop("force_insert", None)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Sengaja tidak melakukan apa-apa.

        Chatbot selalu membutuhkan kata pengantar; menghapusnya akan membuat
        sambutan kosong. Untuk "mengosongkan", panitia menyunting teksnya.
        """
        return 0, {}

    @classmethod
    def ambil(cls) -> "PengaturanSapaan":
        """Baris tunggal — dibuat dengan nilai default kalau belum ada.

        Dipanggil dari jalur request (POST /session), jadi tidak boleh
        melempar DoesNotExist pada instalasi baru.
        """
        obj, _ = cls.objects.get_or_create(pk=cls.ID_TUNGGAL)
        return obj

    def untuk(self, nama: str, sapaan: str = "") -> str:
        """Kalimat sambutan utuh untuk satu camaba.

        Dirakit di sini, bukan di router, supaya widget dan API memakai
        sumber kalimat yang sama persis.
        """
        bagian = [self.salam.strip()]
        if self.pakai_sapaan_gender and sapaan:
            bagian.append(sapaan.strip())
        nama = (nama or "").strip()
        if nama:
            bagian.append(nama)
        awal = " ".join(p for p in bagian if p)
        lanjutan = self.kalimat.strip()
        if not lanjutan:
            return f"{awal}."
        return f"{awal}, {lanjutan}"

    @property
    def pesan_identitas(self) -> str:
        """Jawaban saat camaba bertanya "siapa kamu?".

        Dirakit dari tiga field supaya panitia bisa mengganti nama tanpa
        menulis ulang seluruh kalimat.
        """
        nama = self.nama_bot.strip()
        peran = self.peran_bot.strip()
        kepala = f"Halo! Saya {nama}" if nama else "Halo!"
        if peran:
            kepala += f", {peran}"
        kepala += "."
        lanjutan = self.perkenalan.strip()
        return f"{kepala}\n\n{lanjutan}" if lanjutan else kepala

    def pembuka(self, nama: str, sapaan: str = "") -> list[str]:
        """Dua gelembung pembuka yang dikirim berurutan saat sesi dibuka.

        Yang pertama menyapa camaba dengan namanya, yang kedua memperkenalkan
        chatbot — teks yang sama persis dengan jawaban "siapa kamu?", supaya
        panitia cukup menyunting satu tempat di admin.

        Dikembalikan sebagai list, bukan satu string yang digabung, karena
        widget merendernya sebagai dua gelembung terpisah.
        """
        pesan = [self.untuk(nama, sapaan)]
        identitas = self.pesan_identitas.strip()
        if identitas:
            pesan.append(identitas)
        return pesan
