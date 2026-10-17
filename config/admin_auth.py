"""Daftarkan ulang User & Group dengan tampilan unfold.

django.contrib.auth.admin.UserAdmin memakai `add_form_template` bawaan Django
("admin/auth/user/add_form.html") yang TIDAK mengikuti gaya unfold — akibatnya
form tambah pengguna tampil tanpa gaya dan kolom isiannya nyaris tak terlihat.

Perbaikannya: pakai kelas admin unfold berikut form auth-nya, lalu kosongkan
add_form_template supaya template unfold yang dipakai.
"""

from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as GroupAdminBawaan
from django.contrib.auth.admin import UserAdmin as UserAdminBawaan
from django.contrib.auth.models import Group, User
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(UserAdminBawaan, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    # Kosongkan agar Django tidak memakai template polosnya sendiri.
    add_form_template = None

    list_display = ("username", "email", "first_name", "last_name",
                    "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identitas", {"fields": ("first_name", "last_name", "email")}),
        ("Kewenangan", {
            "fields": ("is_active", "is_staff", "is_superuser",
                       "groups", "user_permissions"),
            "description": (
                "Beri centang <b>Staf</b> agar pengguna bisa masuk panel, "
                "lalu pilih salah satu grup: Editor Konten, Verifikator, "
                "atau Operator."),
        }),
        ("Riwayat", {"fields": ("last_login", "date_joined"),
                     "classes": ("collapse",)}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "password1", "password2"),
        }),
        ("Identitas", {
            "classes": ("wide",),
            "fields": ("first_name", "last_name", "email"),
        }),
        ("Kewenangan", {
            "classes": ("wide",),
            "fields": ("is_active", "is_staff", "groups"),
            "description": (
                "Centang <b>Staf</b> agar pengguna bisa masuk panel, lalu "
                "pilih grup peran."),
        }),
    )


@admin.register(Group)
class GroupAdmin(GroupAdminBawaan, ModelAdmin):
    pass
