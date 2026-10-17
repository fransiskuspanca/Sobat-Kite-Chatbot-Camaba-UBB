"""Buat tiga Group sesuai Bagian 7.5 dokumen rencana.

Django Group + Permission sudah cukup; jangan bangun sistem peran sendiri.
django.contrib.admin.LogEntry otomatis mencatat siapa mengubah apa — jejak
audit yang penting untuk sistem milik PTN.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

# Kewenangan per peran. Nama izin memakai format "app_label.codename".
PERAN = {
    "Editor Konten": {
        "keterangan": "Staf PMB — CRUD FAQ & variasi, lihat antrean. Tidak bisa menyetujui.",
        "izin": [
            "faq.view_faq", "faq.add_faq", "faq.change_faq",
            "faq.view_faqvariasi", "faq.add_faqvariasi",
            "faq.change_faqvariasi", "faq.delete_faqvariasi",
            "percakapan.view_chatlog", "percakapan.view_feedback",
        ],
    },
    "Verifikator": {
        "keterangan": "Kepala unit — semua kewenangan editor + menyetujui jawaban.",
        "izin": [
            "faq.view_faq", "faq.add_faq", "faq.change_faq",
            "faq.dapat_verifikasi",
            "faq.view_faqvariasi", "faq.add_faqvariasi",
            "faq.change_faqvariasi", "faq.delete_faqvariasi",
            "percakapan.view_chatlog", "percakapan.view_feedback",
        ],
    },
    "Operator": {
        "keterangan": "Semua kewenangan + reindex, rollback, akses log penuh.",
        "izin": [
            "faq.view_faq", "faq.add_faq", "faq.change_faq", "faq.delete_faq",
            "faq.dapat_verifikasi", "faq.dapat_reindex",
            "faq.view_faqvariasi", "faq.add_faqvariasi",
            "faq.change_faqvariasi", "faq.delete_faqvariasi",
            "faq.view_indexversion",
            "percakapan.view_chatlog", "percakapan.view_feedback",
        ],
    },
}


class Command(BaseCommand):
    help = "Buat/perbarui Group: Editor Konten, Verifikator, Operator."

    def handle(self, *args, **opts):
        for nama, spek in PERAN.items():
            grup, baru = Group.objects.get_or_create(name=nama)
            izin, hilang = [], []

            for jalur in spek["izin"]:
                app_label, codename = jalur.split(".")
                p = Permission.objects.filter(
                    content_type__app_label=app_label, codename=codename).first()
                (izin.append(p) if p else hilang.append(jalur))

            grup.permissions.set(izin)
            tanda = "dibuat" if baru else "diperbarui"
            self.stdout.write(self.style.SUCCESS(
                f"✅ {nama} {tanda} — {len(izin)} izin"))
            self.stdout.write(f"   {spek['keterangan']}")
            for h in hilang:
                self.stdout.write(self.style.WARNING(f"   ⚠️  izin tidak ada: {h}"))

        self.stdout.write(
            "\nTambahkan pengguna ke grup lewat Admin → Pengguna, "
            "atau: user.groups.add(Group.objects.get(name='Editor Konten'))")
