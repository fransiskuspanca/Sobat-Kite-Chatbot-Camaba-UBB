"""Alat kerja panitia PMB.

Django admin bukan sekadar CRUD di sini. Halaman dirancang mengikuti pekerjaan
panitia, bukan mengikuti tabel — lihat Bagian 7 dokumen rencana.
"""

from datetime import date, timedelta

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.db import models
from django.db.models import Count
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from django import forms

from faq import actions, services
from faq.models import Faq, FaqVariasi, IndexVersion, PengaturanSapaan
from retrieval.tiers import rakit_fallback

# Data PMB kedaluwarsa tiap tahun.
BATAS_KEDALUWARSA = timedelta(days=365)


class VariasiInline(TabularInline):
    """Menambah parafrase harus terasa wajar, bukan fitur tersembunyi."""
    model = FaqVariasi
    fields = ("teks", "asal")
    extra = 3                      # tiga baris kosong, selalu siap diisi
    verbose_name = "Variasi cara bertanya"
    verbose_name_plural = "Variasi cara bertanya"


@admin.register(Faq)
class FaqAdmin(ModelAdmin):
    list_display = ("pertanyaan_singkat", "kategori", "status_verifikasi",
                    "jumlah_variasi", "status_kesegaran", "aksi")
    list_filter = ("butuh_verifikasi", "aktif", "kategori")
    search_fields = ("pertanyaan", "jawaban", "variasi__teks")
    inlines = [VariasiInline]
    actions = ["tandai_terverifikasi", "tandai_butuh_verifikasi",
               "aktifkan", "nonaktifkan", "ekspor_excel"]
    list_per_page = 50
    save_on_top = True
    readonly_fields = ("pratinjau_camaba", "dibuat", "diubah")

    fieldsets = (
        ("Isi", {
            "fields": ("pertanyaan", "jawaban", "pratinjau_camaba"),
        }),
        ("Penggolongan", {
            "fields": ("kategori", "sub_kategori"),
        }),
        ("Sumber", {
            "fields": ("sumber_label", "sumber_url"),
            "description": "Ditampilkan ke camaba di bawah jawaban.",
        }),
        ("Persetujuan unit", {
            "fields": ("butuh_verifikasi", "terakhir_diverifikasi",
                       "berlaku_sampai"),
            "description": (
                "Selama <b>Menunggu persetujuan unit</b> dicentang, jawaban "
                "ini <b>tidak pernah ditampilkan</b> ke camaba — diganti pesan "
                "arahan ke Panitia PMB."),
        }),
        ("Lain-lain", {
            "fields": ("aktif", "dibuat", "diubah"),
            "classes": ("collapse",),
        }),
    )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        # Django 6 mengubah skema default URLField jadi https. Sumber FAQ selalu
        # https, jadi ikuti perilaku baru sekarang agar upgrade nanti mulus.
        if isinstance(db_field, models.URLField):
            kwargs.setdefault("assume_scheme", "https")
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_n_variasi=Count("variasi"))

    def get_changeform_initial_data(self, request):
        """Terima ?pertanyaan=... dari tombol [+ Buat FAQ] di antrean konten.

        Inilah yang menutup lingkaran: admin mengklik satu tombol dan langsung
        mengetik jawaban, tanpa menyalin-tempel pertanyaan camaba.
        """
        awal = super().get_changeform_initial_data(request)
        pertanyaan = request.GET.get("pertanyaan")
        if pertanyaan:
            awal["pertanyaan"] = pertanyaan.strip()[:500]
        return awal

    # --- kolom daftar ---------------------------------------------------

    @display(description="Pertanyaan", ordering="pertanyaan")
    def pertanyaan_singkat(self, obj):
        return obj.pertanyaan if len(obj.pertanyaan) <= 70 \
            else obj.pertanyaan[:70] + "…"

    @display(description="Status", ordering="butuh_verifikasi",
             label={"Menunggu unit": "warning", "Siap tampil": "success",
                    "Nonaktif": "danger"})
    def status_verifikasi(self, obj):
        if not obj.aktif:
            return "Nonaktif"
        return "Menunggu unit" if obj.butuh_verifikasi else "Siap tampil"

    @display(description="Variasi", ordering="_n_variasi")
    def jumlah_variasi(self, obj):
        n = getattr(obj, "_n_variasi", obj.variasi.count())
        # Checklist go-live: setiap FAQ punya minimal 3 variasi.
        warna = "#16a34a" if n >= 3 else ("#ca8a04" if n else "#dc2626")
        return format_html('<b style="color:{}">{}</b>', warna, n)

    @display(description="Diverifikasi", ordering="terakhir_diverifikasi")
    def status_kesegaran(self, obj):
        if obj.terakhir_diverifikasi is None:
            return mark_safe('<span style="color:#9ca3af">—</span>')
        usang = date.today() - obj.terakhir_diverifikasi > BATAS_KEDALUWARSA
        if usang:
            return format_html(
                '<span style="color:#dc2626;font-weight:600">{} ⚠ lebih 12 bln</span>',
                obj.terakhir_diverifikasi.strftime("%d %b %Y"))
        return obj.terakhir_diverifikasi.strftime("%d %b %Y")

    @display(description="Aksi")
    def aksi(self, obj):
        """Tombol langsung dari daftar — tanpa membuka detail dulu.

        Untuk entri yang masih menunggu persetujuan unit, tombol Edit tampil
        menonjol karena itulah pekerjaan yang harus dituntaskan lebih dulu:
        70 dari 260 jawaban masih placeholder.
        """
        url_edit = reverse("admin:faq_faq_change", args=[obj.pk])

        if obj.butuh_verifikasi:
            return format_html(
                '<a href="{}" style="display:inline-block;padding:.3rem .75rem;'
                'background:#f59e0b;color:#fff;border-radius:6px;'
                'text-decoration:none;font-size:.8rem;font-weight:600;'
                'white-space:nowrap" title="Lengkapi jawaban lalu setujui">'
                '✎ Lengkapi</a>', url_edit)

        return format_html(
            '<a href="{}" style="display:inline-block;padding:.3rem .75rem;'
            'border:1px solid #cbd5e1;color:#334155;border-radius:6px;'
            'text-decoration:none;font-size:.8rem;white-space:nowrap">'
            '✎ Edit</a>', url_edit)

    # --- pratinjau -------------------------------------------------------

    @display(description="Seperti apa camaba melihatnya")
    def pratinjau_camaba(self, obj):
        """Menutup jarak antara 'saya mengetik jawaban' dan 'beginilah tampilnya'."""
        if obj.pk is None:
            return "Simpan dulu untuk melihat pratinjau."

        from retrieval.tiers import PESAN_ESKALASI

        if obj.butuh_verifikasi:
            isi = PESAN_ESKALASI
            catatan = ("⚠️ Karena masih menunggu persetujuan unit, camaba "
                       "melihat pesan ini — bukan jawaban Anda.")
            warna = "#f59e0b"
        else:
            isi = obj.jawaban
            sumber = obj.sumber_url or obj.sumber_label
            if sumber and sumber not in {"—", "-"}:
                isi += f"\n\n📎 Sumber: {sumber}"
            catatan = ""
            warna = "#16a34a"

        return format_html(
            '<div style="border-left:4px solid {};background:#f8fafc;'
            'padding:12px 14px;border-radius:6px;max-width:52rem">'
            '<div style="white-space:pre-wrap;line-height:1.55;color:#0f172a">{}</div>'
            '{}</div>',
            warna, isi,
            format_html('<div style="margin-top:10px;color:#b45309;'
                        'font-size:.85rem">{}</div>', catatan) if catatan else "")

    # --- cek tabrakan ----------------------------------------------------

    def save_model(self, request, obj, form, change):
        """Peringatkan bila sangat mirip entri lain — peringatan, BUKAN blokir.

        Admin mungkin punya alasan sah; beri informasi, jangan halangi.
        """
        super().save_model(request, obj, form, change)

        tabrakan = services.cari_tabrakan(obj.pertanyaan, abaikan_pk=obj.pk)
        if not tabrakan:
            return

        atas = tabrakan[0]
        messages.warning(request, format_html(
            'Sangat mirip dengan <a href="{}"><b>“{}”</b></a> '
            '(kemiripan {}). Pertimbangkan menambahkannya sebagai '
            '<b>variasi cara bertanya</b> pada entri itu, daripada membuat '
            'entri baru — dua entri yang mirip membuat chatbot sulit memilih.',
            reverse("admin:faq_faq_change", args=[atas["faq"].pk]),
            atas["faq"].pertanyaan[:80], f"{atas['skor']:.2f}"))

    # --- aksi massal -----------------------------------------------------

    @admin.action(description="Tandai TERVERIFIKASI (siap tampil ke camaba)",
                  permissions=["verifikasi"])
    def tandai_terverifikasi(self, request, queryset):
        n = queryset.update(butuh_verifikasi=False,
                            terakhir_diverifikasi=date.today())
        self.message_user(
            request,
            f"{n} jawaban ditandai terverifikasi dan mulai tampil ke camaba "
            f"setelah index dibangun ulang.", messages.SUCCESS)

    @admin.action(description="Tandai MENUNGGU persetujuan unit",
                  permissions=["verifikasi"])
    def tandai_butuh_verifikasi(self, request, queryset):
        n = queryset.update(butuh_verifikasi=True)
        self.message_user(request,
                          f"{n} jawaban disembunyikan dari camaba.",
                          messages.WARNING)

    @admin.action(description="Aktifkan")
    def aktifkan(self, request, queryset):
        n = queryset.update(aktif=True)
        self.message_user(request, f"{n} entri diaktifkan.", messages.SUCCESS)

    @admin.action(description="Nonaktifkan (keluarkan dari index)")
    def nonaktifkan(self, request, queryset):
        n = queryset.update(aktif=False)
        self.message_user(request, f"{n} entri dinonaktifkan.", messages.WARNING)

    @admin.action(description="Ekspor ke Excel")
    def ekspor_excel(self, request, queryset):
        """Panitia lebih tenang bila bisa mengunduh salinan sendiri —
        dan itu lapis pemulihan tambahan yang gratis (Bagian 11.1)."""
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font

        wb = Workbook()
        ws = wb.active
        ws.title = "FAQ PMB UBB"

        judul = ["No", "Kategori", "Sub-kategori", "Pertanyaan", "Jawaban",
                 "Sumber", "Menunggu unit", "Terakhir diverifikasi",
                 "Variasi cara bertanya", "Aktif"]
        ws.append(judul)
        for sel in ws[1]:
            sel.font = Font(bold=True)

        for i, f in enumerate(queryset.prefetch_related("variasi"), start=1):
            ws.append([
                # `or ""` supaya sel kosong, bukan tulisan "None".
                i, f.kategori or "", f.sub_kategori or "",
                f.pertanyaan, f.jawaban,
                f.sumber_url or f.sumber_label or "",
                "Ya" if f.butuh_verifikasi else "",
                f.terakhir_diverifikasi.strftime("%Y-%m-%d")
                if f.terakhir_diverifikasi else "",
                " | ".join(v.teks for v in f.variasi.all()),
                "Ya" if f.aktif else "Tidak",
            ])

        lebar = [5, 28, 20, 50, 70, 28, 14, 20, 45, 8]
        for kolom, w in zip(ws.columns, lebar):
            ws.column_dimensions[kolom[0].column_letter].width = w
        for baris in ws.iter_rows(min_row=2):
            for sel in baris:
                sel.alignment = Alignment(vertical="top", wrap_text=True)
        ws.freeze_panes = "A2"

        respons = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument"
                         ".spreadsheetml.sheet")
        nama = f"faq-pmb-ubb-{date.today():%Y-%m-%d}.xlsx"
        respons["Content-Disposition"] = f'attachment; filename="{nama}"'
        wb.save(respons)
        return respons

    def has_verifikasi_permission(self, request):
        """Hanya Verifikator & Operator yang boleh menyetujui jawaban."""
        return request.user.has_perm("faq.dapat_verifikasi")


@admin.register(FaqVariasi)
class FaqVariasiAdmin(ModelAdmin):
    list_display = ("teks_singkat", "faq_terkait", "asal", "dibuat")
    list_filter = ("asal", "dibuat")
    search_fields = ("teks", "faq__pertanyaan")
    list_per_page = 50
    autocomplete_fields = ("faq",)

    def get_urls(self):
        return [
            path("laporan-simulasi/",
                 self.admin_site.admin_view(self.laporan_simulasi),
                 name="laporan_simulasi"),
        ] + super().get_urls()

    def laporan_simulasi(self, request):
        """Berapa data hasil simulasi yang sudah masuk (manage.py sinkron_data)."""
        from faq import sinkron

        if not self.has_view_permission(request):
            raise PermissionDenied
        ring = sinkron.ringkasan_status()
        # Waktu disimpan dalam UTC; tampilkan dalam zona waktu server (WIB).
        from datetime import datetime

        from django.utils import timezone
        for p in ring["paket"]:
            try:
                p["waktu"] = timezone.localtime(datetime.fromisoformat(p["waktu"]))
            except (KeyError, TypeError, ValueError):
                p["waktu"] = None
        konteks = {
            **self.admin_site.each_context(request),
            "title": "Laporan data simulasi",
            **ring,
            "variasi_aktif": FaqVariasi.objects.filter(asal="augmentasi").count(),
            "variasi_log": FaqVariasi.objects.filter(asal="log").count(),
            "menunggu": Faq.objects.filter(butuh_verifikasi=True, aktif=True).count(),
            "url_variasi": reverse("admin:faq_faqvariasi_changelist") + "?asal__exact=augmentasi",
            "url_menunggu": reverse("admin:faq_faq_changelist") + "?butuh_verifikasi__exact=1",
        }
        return render(request, "admin/faq/laporan_simulasi.html", konteks)

    @display(description="Variasi", ordering="teks")
    def teks_singkat(self, obj):
        return obj.teks if len(obj.teks) <= 80 else obj.teks[:80] + "…"

    @display(description="Menjawab pertanyaan", ordering="faq__pertanyaan")
    def faq_terkait(self, obj):
        return format_html('<a href="{}">{}</a>',
                           reverse("admin:faq_faq_change", args=[obj.faq_id]),
                           obj.faq.pertanyaan[:70])


@admin.register(IndexVersion)
class IndexVersionAdmin(ModelAdmin):
    """Read-only di Fase 1. Tombol reindex & rollback menyusul di Fase 3.

    Halaman ini adalah alat OPERATOR, bukan alat panitia PMB: isinya versi
    index beserta skor regression gate, dan satu-satunya jalan rollback saat
    chatbot menjawab ngawur setelah update. Istilahnya teknis dan tidak ada
    hubungannya dengan pekerjaan mengurasi FAQ, jadi disembunyikan dari
    Editor Konten & Verifikator (Bagian 7.5: reindex/rollback = Operator).
    """
    list_display = ("versi", "jumlah_vektor", "jumlah_answer", "akurasi",
                    "status", "dibuat", "aksi_rollback")
    readonly_fields = ("versi", "pemilik", "dim", "jumlah_vektor",
                       "jumlah_answer", "acc_at_1", "catatan", "aktif", "dibuat")
    exclude = ("vektor",)          # blob biner, tidak berguna ditampilkan
    list_per_page = 30

    change_list_template = "admin/faq/indexversion/change_list.html"

    def has_add_permission(self, request):
        return False               # index dibuat lewat reindex, bukan diketik

    # --- tombol reindex & rollback (Fase 3) -----------------------------

    def get_urls(self):
        return [
            path("reindex/", self.admin_site.admin_view(self.mulai_reindex),
                 name="faq_indexversion_reindex"),
            path("status/",
                 self.admin_site.admin_view(self.status_reindex_json),
                 name="faq_indexversion_status"),
            path("<int:versi>/rollback/",
                 self.admin_site.admin_view(self.lakukan_rollback),
                 name="faq_indexversion_rollback"),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        # Tombol rollback dirender per baris, jadi tokennya disiapkan di sini.
        self._token = get_token(request)
        hard_eval = settings.ARTIFACTS_DIR / "hard_eval.json"
        extra_context = {
            **(extra_context or {}),
            "status_reindex": actions.status_reindex().sebagai_dict(),
            # Bagian 9.4: jangan sampai admin mengira terlindungi padahal belum.
            "gate_aktif": hard_eval.exists(),
            "ambang_acc": actions.ambang_default(),
        }
        return super().changelist_view(request, extra_context)

    def mulai_reindex(self, request):
        if not self._operator(request):
            raise PermissionDenied
        if request.method != "POST":
            return redirect("admin:faq_indexversion_changelist")

        paksa = request.POST.get("paksa") == "1"
        dimulai = actions.mulai_reindex_latar(
            paksa=paksa, pengguna=request.user.get_username())

        if dimulai:
            self.message_user(
                request,
                "Pembangunan ulang index dimulai. Halaman ini memperbarui "
                "statusnya sendiri — proses berjalan di latar, aman ditinggal.",
                messages.INFO)
        else:
            self.message_user(request, "Reindex lain sedang berjalan.",
                              messages.WARNING)
        return redirect("admin:faq_indexversion_changelist")

    def status_reindex_json(self, request):
        """Dipanggil berkala oleh halaman selama reindex berjalan.

        Namanya sengaja BUKAN `status` — itu sudah dipakai kolom tabel, dan
        method kedua akan menimpa yang pertama tanpa peringatan apa pun.
        """
        if not self._operator(request):
            raise PermissionDenied
        return JsonResponse(actions.status_reindex().sebagai_dict())

    def lakukan_rollback(self, request, versi):
        if not self._operator(request):
            raise PermissionDenied
        if request.method != "POST":
            return redirect("admin:faq_indexversion_changelist")

        try:
            iv = actions.rollback(versi, pengguna=request.user.get_username())
        except IndexVersion.DoesNotExist:
            self.message_user(request, f"Versi {versi} tidak ditemukan.",
                              messages.ERROR)
        else:
            self.message_user(
                request,
                f"Index dikembalikan ke v{iv.versi} ({iv.jumlah_vektor} vektor). "
                "Worker API menyusul dalam beberapa detik.",
                messages.SUCCESS)
        return redirect("admin:faq_indexversion_changelist")

    def has_module_permission(self, request):
        """Sembunyikan seluruh menu dari yang bukan Operator."""
        return self._operator(request)

    def has_view_permission(self, request, obj=None):
        return self._operator(request)

    @staticmethod
    def _operator(request):
        return (request.user.is_superuser
                or request.user.has_perm("faq.dapat_reindex"))

    @admin.display(description="Acc@1", ordering="acc_at_1")
    def akurasi(self, obj):
        if obj.acc_at_1 is None:
            return format_html('<span style="color:#ca8a04">belum diuji</span>')
        warna = "#16a34a" if obj.acc_at_1 >= 0.85 else "#dc2626"
        # format_html meng-escape argumen jadi SafeString, sehingga spesifier
        # angka seperti {:.3f} gagal. Format dulu, baru serahkan.
        return format_html('<b style="color:{}">{}</b>', warna,
                           f"{obj.acc_at_1:.3f}")

    @admin.display(description="Aksi")
    def aksi_rollback(self, obj):
        """Rollback: langkah pertama saat chatbot menjawab ngawur.

        Tidak ada encode ulang — vektornya sudah tersimpan di basis data,
        jadi pemulihan berlangsung seketika.
        """
        if obj.aktif:
            return mark_safe('<span style="color:#9ca3af">sedang dipakai</span>')

        url = reverse("admin:faq_indexversion_rollback", args=[obj.versi])
        return format_html(
            '<form method="post" action="{}" style="margin:0" '
            'onsubmit="return confirm(\'Kembalikan index ke v{}? '
            'Camaba akan langsung dilayani versi ini.\')">'
            '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
            '<button type="submit" style="padding:.3rem .75rem;border:1px solid '
            '#cbd5e1;background:#fff;color:#334155;border-radius:6px;'
            'font-size:.8rem;cursor:pointer;white-space:nowrap">'
            '↩ Rollback</button></form>',
            url, obj.versi, self._token)

    @admin.display(description="Status", ordering="aktif")
    def status(self, obj):
        if obj.aktif:
            return mark_safe('<b style="color:#16a34a">● AKTIF</b>')
        return mark_safe('<span style="color:#9ca3af">—</span>')


class PengaturanSapaanForm(forms.ModelForm):
    """Validasi placeholder sebelum teks dipakai camaba.

    Kalau panitia salah ketik ({kata}, {kunci pertanyaan}), .format() akan
    melempar dan setiap fallback jatuh ke teks bawaan — gejalanya sunyi:
    perubahan di admin "tidak berefek" tanpa pesan error apa pun. Lebih baik
    ditolak di sini.
    """

    class Meta:
        model = PengaturanSapaan
        fields = "__all__"

    def clean_fallback_template(self):
        teks = (self.cleaned_data.get("fallback_template") or "").strip()
        if not teks:
            return teks          # kosong = pakai bawaan, itu sah
        if "{kunci}" not in teks:
            raise forms.ValidationError(
                "Harus memuat {kunci} — tanpa itu jawaban tidak menyebut "
                "pertanyaan camaba. Kosongkan kalau memang tidak mau "
                "menyebutnya.")
        try:
            teks.format(kunci="contoh")
        except (KeyError, IndexError, ValueError):
            raise forms.ValidationError(
                "Ada tanda { } lain yang tidak dikenali. Placeholder yang "
                "tersedia hanya {kunci}.")
        return teks

    def clean_fallback_tanpa_kunci(self):
        teks = (self.cleaned_data.get("fallback_tanpa_kunci") or "").strip()
        if "{kunci}" in teks:
            raise forms.ValidationError(
                "Kolom ini dipakai justru saat tidak ada kata kunci, jadi "
                "{kunci} akan tampil apa adanya. Hapus placeholder-nya.")
        return teks


@admin.register(PengaturanSapaan)
class PengaturanSapaanAdmin(ModelAdmin):
    """Halaman PENGATURAN, bukan daftar.

    Isinya tepat satu baris, jadi changelist tidak ada gunanya: setiap jalan
    masuk (menu, /add/, /change/ id apa pun) dibelokkan ke form baris tunggal
    itu. Panitia cukup melihat satu form, menyunting, simpan — sama seperti
    halaman setelan pada umumnya.
    """

    fieldsets = (
        ("Kata pengantar pembuka", {
            "fields": ("salam", "kalimat", "pakai_sapaan_gender"),
            "description": "Kalimat sambutan yang muncul saat camaba pertama "
                           "kali membuka chatbot.",
        }),
        ("Identitas chatbot", {
            "fields": ("nama_bot", "peran_bot", "perkenalan"),
            "description": "Dipakai saat camaba bertanya \"siapa kamu?\".",
        }),
        ("Jawaban di luar konteks", {
            "fields": ("fallback_template", "fallback_tanpa_kunci"),
            "description": "Dipakai saat pertanyaan camaba di luar cakupan "
                           "PMB UBB. Tulis <code>{kunci}</code> di tempat "
                           "inti pertanyaan camaba akan disisipkan.",
        }),
        ("Pratinjau", {"fields": ("pratinjau", "pratinjau_pembuka",
                                  "pratinjau_identitas", "pratinjau_fallback")}),
    )
    readonly_fields = ("pratinjau", "pratinjau_pembuka",
                       "pratinjau_identitas", "pratinjau_fallback")
    form = PengaturanSapaanForm

    def has_add_permission(self, request):
        # Baris tunggal — menambah baris kedua tidak punya arti.
        return False

    def has_delete_permission(self, request, obj=None):
        # Chatbot selalu perlu kata pengantar; tanpa baris ini sambutan kosong.
        return False

    @display(description="Tampil ke camaba seperti ini")
    def pratinjau(self, obj):
        """Contoh nyata untuk dua jenis kelamin.

        Panitia menyunting template, bukan kalimat jadi — tanpa pratinjau
        mereka harus membuka widget hanya untuk tahu hasilnya.
        """
        if obj is None or obj.pk is None:
            return "—"
        return format_html(
            '<div style="line-height:1.9">'
            '<div><strong>Camaba laki-laki:</strong> {}</div>'
            '<div><strong>Camaba perempuan:</strong> {}</div>'
            "</div>",
            obj.untuk("Budi Santoso", "Bang"),
            obj.untuk("Siti Aminah", "Kak"))

    @display(description="Urutan gelembung saat chatbot dibuka")
    def pratinjau_pembuka(self, obj):
        """Camaba menerima dua pesan berurutan, bukan satu.

        Pratinjau terpisah karena gelembung kedua dirakit dari field
        "Identitas chatbot" di bawah — tanpa ini panitia tidak sadar kedua
        bagian form itu muncul bersamaan di layar camaba.
        """
        if obj is None or obj.pk is None:
            return "—"
        gelembung = format_html_join(
            "", '<div style="background:#f3f4f6;border-radius:12px;'
                'padding:10px 14px;margin-bottom:8px;max-width:34rem;'
                'white-space:pre-wrap">{}</div>',
            ((teks,) for teks in obj.pembuka("Budi Santoso", "Bang")))
        return format_html('<div style="line-height:1.7">{}</div>', gelembung)

    @display(description="Contoh jawaban di luar konteks")
    def pratinjau_fallback(self, obj):
        """Pertanyaan nyata yang pernah masuk, supaya panitia lihat hasilnya.

        Tanpa ini panitia harus menebak apa yang menggantikan {kunci}; contoh
        konkret jauh lebih cepat dipahami daripada penjelasan help_text.
        """
        if obj is None or obj.pk is None:
            return "—"
        contoh = ("prabowo subianto", "warna gedung telkom?",
                  "apa itu resep rendang padang", "???")
        baris = format_html_join(
            "", '<div style="margin-bottom:10px">'
                '<div style="color:#6b7280">camaba: {}</div>'
                '<div style="background:#fef2f2;border-radius:12px;'
                'padding:10px 14px;max-width:34rem;white-space:pre-wrap">'
                "{}</div></div>",
            ((q, rakit_fallback(q, obj.fallback_template,
                                obj.fallback_tanpa_kunci)) for q in contoh))
        return format_html('<div style="line-height:1.7">{}</div>', baris)

    @display(description="Jawaban saat ditanya \"siapa kamu?\"")
    def pratinjau_identitas(self, obj):
        if obj is None or obj.pk is None:
            return "—"
        return format_html('<div style="white-space:pre-wrap;line-height:1.7">'
                           "{}</div>", obj.pesan_identitas)

    # --- semua jalan menuju satu baris ----------------------------------

    def changelist_view(self, request, extra_context=None):
        """Menu mengarah ke sini; belokkan langsung ke form-nya."""
        obj = PengaturanSapaan.ambil()
        return redirect(reverse("admin:faq_pengaturansapaan_change",
                                args=[obj.pk]))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """Id apa pun di URL tetap membuka baris tunggal itu."""
        obj = PengaturanSapaan.ambil()
        if str(object_id) != str(obj.pk):
            return redirect(reverse("admin:faq_pengaturansapaan_change",
                                    args=[obj.pk]))
        extra_context = {**(extra_context or {}),
                         "title": "Kata pengantar pembuka",
                         # Halaman setelan: tidak ada daftar untuk kembali.
                         "show_save_and_add_another": False,
                         "show_save_and_continue": True,
                         "show_delete_link": False}
        return super().change_view(request, object_id, form_url, extra_context)

    def response_change(self, request, obj):
        """Setelah simpan, kembali ke form yang sama — bukan ke changelist.

        Changelist akan memantulkan balik ke sini, jadi redirect bawaan
        Django hanya menambah satu lompatan yang tidak perlu.
        """
        if "_continue" not in request.POST and "_saveasnew" not in request.POST:
            messages.success(request, "Kata pengantar pembuka telah disimpan.")
            return redirect(reverse("admin:faq_pengaturansapaan_change",
                                    args=[obj.pk]))
        return super().response_change(request, obj)
