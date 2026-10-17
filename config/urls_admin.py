"""Hanya /admin/* + /static/* (Bagian 3 dokumen rencana)."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView

# Menimpa pendaftaran User/Group bawaan dengan versi bergaya unfold.
from config import admin_auth  # noqa: F401

admin.site.site_header = "Chatbot PMB UBB"
admin.site.site_title = "Chatbot PMB UBB"
admin.site.index_title = "Panel Panitia PMB"

urlpatterns = [
    path("admin/", admin.site.urls),
    # Panitia mengetik domainnya saja, bukan "/admin". Arahkan ke panel supaya
    # tidak mendarat di halaman kosong / debug Django.
    path("", RedirectView.as_view(url="/admin/", permanent=False), name="root"),
]

# Aset statis di dev server; di produksi Nginx yang melayani /static/.
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL,
                          document_root=settings.STATIC_ROOT)
