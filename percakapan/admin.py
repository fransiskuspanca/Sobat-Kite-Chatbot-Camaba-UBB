"""Log percakapan (read-only) + antrean konten.

Antrean konten menutup lingkaran: camaba bertanya -> sistem gagal -> admin
melihat -> konten ditambahkan -> camaba berikutnya terjawab. Inilah alasan
utama sistem membaik seiring waktu (Bagian 7.3).
"""

from django.contrib import admin, messages
from django.db.models import Avg, Count, Max, Q
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.timesince import timesince
from unfold.admin import ModelAdmin
from unfold.decorators import display

from percakapan.models import ChatLog, Feedback, Sesi

# Tipe yang menandakan sistem TIDAK berhasil menjawab.
TIPE_GAGAL = ("fallback", "klarifikasi")

# Jawaban yang diberi 👎 juga gagal — chatbot yakin, tapi tidak nyambung.
FILTER_GAGAL = Q(tipe__in=TIPE_GAGAL) | Q(feedback__rating="down")

SARAN_MAKS = 3


def _saran_faq(query: str) -> list[dict]:
    """FAQ terdekat untuk `query`, supaya panitia cukup memilih, bukan mencari.

    Engine mati tidak boleh membuat antrean gagal dibuka — saran kosong saja.
    """
    from faq.models import Faq
    from faq.services import engine_siap

    try:
        engine = engine_siap()
        hits = engine.cari(query, top_k=SARAN_MAKS) if engine else []
    except Exception:
        return []
    peta = Faq.objects.in_bulk([fid for fid, _ in hits])
    return [{"id": fid, "pertanyaan": peta[fid].pertanyaan, "skor": s}
            for fid, s in hits if fid in peta]


@admin.register(ChatLog)
class ChatLogAdmin(ModelAdmin):
    """Read-only — log adalah catatan kejadian, bukan data yang disunting."""

    list_display = ("query_singkat", "tipe_berlabel", "skor_terformat",
                    "faq_terkait", "camaba", "dibuat")
    list_filter = ("tipe", "dibuat")
    search_fields = ("query", "log_id", "session_id")
    date_hierarchy = "dibuat"
    list_per_page = 50
    readonly_fields = tuple(f.name for f in ChatLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # --- kolom ----------------------------------------------------------

    @display(description="Pertanyaan camaba", ordering="query")
    def query_singkat(self, obj):
        return obj.query if len(obj.query) <= 70 else obj.query[:70] + "…"

    @display(description="Hasil", ordering="tipe",
             label={"jawaban": "success", "sapaan": "info",
                    "identitas": "info",
                    "klarifikasi": "warning", "eskalasi": "warning",
                    "fallback": "danger"})
    def tipe_berlabel(self, obj):
        return obj.tipe

    @display(description="Skor", ordering="skor")
    def skor_terformat(self, obj):
        return f"{obj.skor:.4f}"

    @display(description="Camaba")
    def camaba(self, obj):
        """Siapa yang bertanya — kosong untuk log lama tanpa sesi."""
        if obj.sesi_id is None:
            return "—"
        return format_html('<a href="{}">{}</a>',
                           reverse("admin:percakapan_sesi_change",
                                   args=[obj.sesi_id]),
                           obj.sesi.nama_lengkap)

    @display(description="FAQ tercocok")
    def faq_terkait(self, obj):
        if obj.faq_id is None:
            return "—"
        return format_html('<a href="{}">{}</a>',
                           reverse("admin:faq_faq_change", args=[obj.faq_id]),
                           obj.faq.pertanyaan[:50])

    def get_queryset(self, request):
        # Kolom camaba & FAQ dirender per-baris; tanpa ini list view
        # menembak satu query tambahan untuk tiap log.
        return super().get_queryset(request).select_related("sesi", "faq")

    # --- halaman antrean konten -----------------------------------------

    def get_urls(self):
        return [
            path("antrean/", self.admin_site.admin_view(self.antrean_konten),
                 name="antrean_konten"),
            path("antrean/tautkan/",
                 self.admin_site.admin_view(self.tautkan_ke_faq),
                 name="antrean_tautkan"),
            path("statistik/", self.admin_site.admin_view(self.statistik),
                 name="statistik_percakapan"),
        ] + super().get_urls()

    def statistik(self, request):
        """Ringkasan operasional (Bagian 11.3).

        Yang benar-benar perlu diawasi: RASIO FALLBACK. Kalau naik tiba-tiba,
        ada yang salah — bisa kesalahan reindex, bisa musim bertanya baru yang
        belum tercakup FAQ.
        """
        from datetime import timedelta

        from django.db.models.functions import TruncDate
        from django.utils import timezone

        sejak = timezone.now() - timedelta(days=30)
        qs = ChatLog.objects.filter(dibuat__gte=sejak)
        total = qs.count()

        per_tipe = list(qs.values("tipe").annotate(n=Count("log_id"))
                        .order_by("-n"))
        n_gagal = sum(t["n"] for t in per_tipe if t["tipe"] in TIPE_GAGAL)

        per_hari = list(
            qs.annotate(tanggal=TruncDate("dibuat"))
              .values("tanggal")
              .annotate(n=Count("log_id"),
                        gagal=Count("log_id", filter=Q(tipe__in=TIPE_GAGAL)))
              .order_by("-tanggal")[:14])
        for h in per_hari:
            h["rasio"] = (h["gagal"] / h["n"] * 100) if h["n"] else 0

        umpan = Feedback.objects.filter(log__dibuat__gte=sejak)
        n_up = umpan.filter(rating="up").count()
        n_down = umpan.filter(rating="down").count()

        latensi = sorted(qs.exclude(latency_ms__isnull=True)
                         .values_list("latency_ms", flat=True))
        p95 = latensi[int(len(latensi) * 0.95)] if latensi else None

        konteks = {
            **self.admin_site.each_context(request),
            "title": "Statistik percakapan — 30 hari terakhir",
            "total": total,
            "per_tipe": per_tipe,
            "rasio_gagal": (n_gagal / total * 100) if total else 0,
            "per_hari": per_hari,
            "n_up": n_up,
            "n_down": n_down,
            "rasio_puas": (n_up / (n_up + n_down) * 100) if (n_up + n_down) else None,
            "p95": p95,
            "median": latensi[len(latensi) // 2] if latensi else None,
        }
        return render(request, "admin/percakapan/statistik.html", konteks)

    def antrean_konten(self, request):
        """Pertanyaan camaba yang gagal dijawab, dikelompokkan & diurutkan.

        Frekuensi tinggi = kekosongan konten yang paling merugikan. Itu yang
        harus dikerjakan panitia lebih dulu. Pertanyaan yang sudah ditautkan
        sebagai variasi tidak tampil lagi.
        """
        from faq.models import FaqVariasi

        sudah = {" ".join(t.lower().split())
                 for t in FaqVariasi.objects.values_list("teks", flat=True)}
        baris = (ChatLog.objects
                 .filter(FILTER_GAGAL)
                 .values("query")
                 .annotate(frekuensi=Count("log_id", distinct=True),
                           jempol_bawah=Count("log_id", distinct=True,
                                              filter=Q(feedback__rating="down")),
                           skor_rata=Avg("skor"),
                           terakhir=Max("dibuat"))
                 .order_by("-frekuensi", "-terakhir")[:200])
        baris = [b for b in baris
                 if " ".join(b["query"].lower().split()) not in sudah][:100]

        tambah_url = reverse("admin:faq_faq_add")
        antrean = [{
            "query": b["query"],
            "frekuensi": b["frekuensi"],
            "jempol_bawah": b["jempol_bawah"],
            "skor_rata": b["skor_rata"] or 0.0,
            "terakhir": timesince(b["terakhir"]) + " lalu" if b["terakhir"] else "—",
            # Tombol membuka form tambah dengan pertanyaan SUDAH TERISI.
            "url_buat": f"{tambah_url}?pertanyaan={b['query']}",
            "saran": _saran_faq(b["query"]),
        } for b in baris]

        konteks = {
            **self.admin_site.each_context(request),
            "title": "Antrean konten — pertanyaan yang belum terjawab",
            "antrean": antrean,
            "total": len(antrean),
            "url_tautkan": reverse("admin:antrean_tautkan"),
        }
        return render(request, "admin/percakapan/antrean_konten.html", konteks)

    def tautkan_ke_faq(self, request):
        """Jadikan pertanyaan camaba sebagai variasi FAQ yang dipilih panitia.

        Index baru terpasang pada reindex berikutnya (cron malam), lewat
        regression gate seperti biasa.
        """
        from faq.models import Faq, FaqVariasi

        tujuan = reverse("admin:antrean_konten")
        if request.method != "POST":
            return redirect(tujuan)
        if not request.user.has_perm("faq.add_faqvariasi"):
            messages.error(request, "Anda tidak berhak menambah variasi.")
            return redirect(tujuan)

        query = " ".join(request.POST.get("query", "").split())[:500]
        faq = Faq.objects.filter(pk=request.POST.get("faq_id") or 0).first()
        if not query or faq is None:
            messages.error(request, "Pertanyaan atau FAQ tujuan tidak valid.")
            return redirect(tujuan)

        _, baru = FaqVariasi.objects.get_or_create(
            faq=faq, teks=query, defaults={"asal": "log"})
        messages.success(
            request,
            f"“{query}” ditautkan ke “{faq.pertanyaan}”. "
            "Berlaku setelah reindex berikutnya." if baru else
            f"“{query}” sudah menjadi variasi “{faq.pertanyaan}”.")
        return redirect(tujuan)


@admin.register(Feedback)
class FeedbackAdmin(ModelAdmin):
    list_display = ("rating", "query_terkait", "komentar_singkat", "dibuat")
    list_filter = ("rating", "dibuat")
    search_fields = ("komentar", "log__query")
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    @display(description="Pertanyaan")
    def query_terkait(self, obj):
        return obj.log.query[:60]

    @display(description="Komentar")
    def komentar_singkat(self, obj):
        return obj.komentar[:70] if obj.komentar else "—"


@admin.register(Sesi)
class SesiAdmin(ModelAdmin):
    """Daftar calon camaba — read-only.

    Isinya persis apa yang camaba ketik sendiri di form profil sebelum
    bertanya. Panitia hanya membacanya (mis. untuk menghubungi balik camaba
    yang pertanyaannya masuk antrean konten), tidak menyuntingnya.
    """

    list_display = ("nomor", "nama_lengkap", "jenis_kelamin_berlabel",
                    "email_camaba", "waktu")
    list_filter = ("jenis_kelamin", "dibuat")
    search_fields = ("nama_lengkap", "email", "session_id")
    date_hierarchy = "dibuat"
    list_per_page = 50
    ordering = ["-dibuat"]
    readonly_fields = tuple(f.name for f in Sesi._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return (super().get_queryset(request)
                .annotate(n_tanya=Count("log")))

    # --- kolom ----------------------------------------------------------

    @display(description="Nomor")
    def nomor(self, obj):
        """Nomor urut tampilan, dihitung dari posisi baris di halaman ini.

        Sengaja BUKAN id: primary key sesi berupa heksadesimal 32 karakter
        yang tidak berarti apa-apa bagi panitia. Nomor mengikuti urutan dan
        halaman yang sedang dilihat.
        """
        return getattr(obj, "_nomor_urut", "—")

    @display(description="Jenis kelamin", ordering="jenis_kelamin",
             label={"Laki-laki": "info", "Perempuan": "success"})
    def jenis_kelamin_berlabel(self, obj):
        return obj.get_jenis_kelamin_display()

    @display(description="Email", ordering="email")
    def email_camaba(self, obj):
        """Email opsional — banyak camaba mengosongkannya."""
        if not obj.email:
            return "—"
        return format_html('<a href="mailto:{}">{}</a>', obj.email, obj.email)

    @display(description="Waktu", ordering="dibuat")
    def waktu(self, obj):
        return obj.dibuat

    @display(description="Pertanyaan", ordering="n_tanya")
    def jumlah_pertanyaan(self, obj):
        return obj.n_tanya

    def changelist_view(self, request, extra_context=None):
        """Menempelkan nomor urut ke tiap baris sebelum dirender.

        Nomor dihitung di sini, bukan di dalam kolom: dipanggil per-baris ia
        tidak tahu posisinya sendiri di halaman. Nilainya ditempel ke OBJEK,
        bukan ke self — instance ModelAdmin dipakai bersama lintas request,
        jadi menyimpan state di sana bisa tertukar antar-pengguna.
        """
        response = super().changelist_view(request, extra_context)
        cl = getattr(response, "context_data", {}).get("cl")
        if cl is not None:
            # page_num 1-indexed sejak Django 4.1 — halaman pertama = 1.
            awal = (cl.page_num - 1) * self.list_per_page
            for i, obj in enumerate(cl.result_list, start=1):
                obj._nomor_urut = awal + i
        return response
