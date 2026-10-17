"""Endpoint publik yang dipanggil widget di pmb.ubb.ac.id.

Endpoint publiknya sedikit dan tetap (Bagian 8): /session, /query, /history,
/feedback, /health. Endpoint admin TIDAK diekspos sebagai API — semuanya lewat
Django admin, sehingga permukaan serangan jauh lebih kecil.
"""

from __future__ import annotations

import logging
import time
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError as ValidasiDjango
from django.core.validators import validate_email
from ninja import NinjaAPI, Router
from ninja.errors import ValidationError

from api.schemas import (RIWAYAT_MAKS, ChatQueryData, ChatQueryRequest,
                         Envelope, FeedbackData, FeedbackRequest, HealthData,
                         RiwayatData, SesiData, SesiRequest)
from api.throttle import lewat_batas

log = logging.getLogger(__name__)

api = NinjaAPI(
    title="API Chatbot Camaba UBB",
    version="1.0.0",
    urls_namespace="api",
    # Matikan docs di produksi — mengurangi permukaan serangan.
    docs_url=None if not settings.DEBUG else "/docs",
)

chat = Router(tags=["chat"])


# --- penanganan galat: jangan pernah membocorkan traceback ---------------

@api.exception_handler(ValidationError)
def galat_validasi(request, exc):
    return api.create_response(
        request,
        {"sukses": False, "data": None,
         "pesan": "Pertanyaan tidak valid. Panjang maksimal 500 karakter."},
        status=422)


@api.exception_handler(Exception)
def galat_tak_terduga(request, exc):
    """Prinsip #6: layanan tetap sopan, bukan HTTP 500 telanjang."""
    log.exception("Galat tak tertangani di %s", request.path)
    from retrieval.tiers import PESAN_LAYANAN_SIBUK
    return api.create_response(
        request, {"sukses": False, "data": None, "pesan": PESAN_LAYANAN_SIBUK},
        status=503)


# --- helper --------------------------------------------------------------

def _tolak_karena_ramai(request):
    return api.create_response(
        request,
        {"sukses": False, "data": None,
         "pesan": "Terlalu banyak permintaan. Coba lagi sebentar lagi."},
        status=429)


def _metadata_faq(ids: list[int]) -> dict[int, dict]:
    """Ambil metadata FAQ untuk kandidat hasil pencarian.

    Disuntikkan ke engine agar retrieval/ tetap tidak mengenal Django.
    """
    from faq.models import Faq

    keluar = {}
    for f in Faq.objects.filter(id__in=ids, aktif=True):
        keluar[f.id] = {
            "pertanyaan": f.pertanyaan,
            "jawaban": f.jawaban,
            "kategori": f.kategori,
            "sumber_label": f.sumber_label,
            "sumber_url": f.sumber_url,
            "butuh_verifikasi": f.butuh_verifikasi,
            "terakhir_diverifikasi": (f.terakhir_diverifikasi.isoformat()
                                      if f.terakhir_diverifikasi else None),
        }
    return keluar


def _ambil_sesi(session_id: str | None):
    """Sesi yang valid, atau None.

    session_id tak dikenal (localStorage basi, sesi sudah dihapus) BUKAN
    galat: camaba tetap dilayani, hanya riwayatnya yang tidak tersambung.
    """
    if not session_id:
        return None
    from percakapan.models import Sesi

    try:
        return Sesi.objects.filter(pk=session_id[:64]).first()
    except Exception:
        log.exception("Gagal mengambil Sesi %s", session_id)
        return None


# Pertanyaan lanjutan hanya disambung ke jawaban yang masih hangat; setelah
# jeda panjang camaba biasanya sudah berganti topik.
KONTEKS_MAKS_MENIT = 30


def _konteks_sesi(sesi) -> tuple[str, int | None]:
    """(pertanyaan FAQ, faq_id) yang terakhir dijawab dalam sesi, atau ("", None)."""
    if sesi is None:
        return "", None
    from datetime import timedelta

    from django.utils import timezone

    from percakapan.models import ChatLog

    try:
        terakhir = (ChatLog.objects
                    .filter(session_id=sesi.pk, faq__isnull=False,
                            dibuat__gte=timezone.now()
                            - timedelta(minutes=KONTEKS_MAKS_MENIT))
                    .select_related("faq").order_by("-dibuat").first())
    except Exception:
        log.exception("Gagal mengambil konteks sesi %s", sesi.pk)
        return "", None
    if terakhir is None:
        return "", None
    return terakhir.faq.pertanyaan, terakhir.faq_id


def _catat_log(*, log_id, query, keputusan, session_id, sesi, index_version,
               latency_ms):
    """Simpan ChatLog. Aset terbesar sistem ini — tapi gagal mencatat TIDAK
    boleh menggagalkan jawaban ke camaba."""
    from faq.models import Faq
    from percakapan.models import ChatLog

    try:
        ChatLog.objects.create(
            log_id=log_id,
            query=query[:2000],
            tipe=str(keputusan.tipe),
            skor=keputusan.skor,
            faq=(Faq.objects.filter(pk=keputusan.faq_id).first()
                 if keputusan.faq_id else None),
            session_id=(session_id or "")[:64],
            sesi=sesi,
            # Disimpan apa adanya supaya GET /history bisa menampilkan ulang
            # persis apa yang dulu dibaca camaba, walau FAQ-nya sudah disunting.
            jawaban=keputusan.jawaban or "",
            index_version=index_version,
            latency_ms=latency_ms,
            cached=False,
        )
    except Exception:
        # Log adalah aset, tapi camaba yang sudah punya jawaban tidak boleh
        # kehilangannya hanya karena pencatatan gagal (prinsip #6).
        log.exception("Gagal mencatat ChatLog %s", log_id)


# --- POST /v1/chat/query -------------------------------------------------

@chat.post("/query", response=Envelope[ChatQueryData], summary="Tanya chatbot")
def query(request, payload: ChatQueryRequest):
    if lewat_batas(request):
        return _tolak_karena_ramai(request)

    mulai = time.perf_counter()
    log_id = uuid.uuid4().hex[:32]

    sesi = _ambil_sesi(payload.session_id)

    from faq.services import engine_siap
    from retrieval.tiers import keputusan_darurat

    engine = engine_siap()
    if engine is None:
        # Model/index tidak tersedia -> pesan sopan, bukan 500 (prinsip #6).
        keputusan = keputusan_darurat()
        versi = None
    else:
        # Identitas chatbot & teks fallback diambil dari pengaturan admin.
        # Kegagalan membaca tidak boleh menjatuhkan jawaban — tier identitas
        # cukup dilewati dan fallback memakai teks bawaan.
        try:
            from faq.models import PengaturanSapaan
            p = PengaturanSapaan.ambil()
            pesan_identitas = p.pesan_identitas
            template_fallback = p.fallback_template
            fallback_tanpa_kunci = p.fallback_tanpa_kunci
        except Exception:
            log.exception("Gagal membaca pengaturan identitas")
            pesan_identitas = template_fallback = fallback_tanpa_kunci = ""
        konteks, faq_sebelumnya = _konteks_sesi(sesi)
        keputusan = engine.jawab(payload.query, _metadata_faq, pesan_identitas,
                                 template_fallback, fallback_tanpa_kunci,
                                 konteks=konteks, faq_sebelumnya=faq_sebelumnya)
        versi = engine.snapshot.versi if engine.snapshot else None

    latency = int((time.perf_counter() - mulai) * 1000)

    try:
        _catat_log(log_id=log_id, query=payload.query, keputusan=keputusan,
                   session_id=payload.session_id, sesi=sesi,
                   index_version=versi, latency_ms=latency)
    except Exception:
        log.exception("Pencatatan log gagal total untuk %s", log_id)

    if sesi is not None:
        # Menandai sesi masih hidup; kegagalan di sini tidak boleh menahan
        # jawaban yang sudah siap.
        try:
            sesi.save(update_fields=["terakhir_aktif"])
        except Exception:
            log.exception("Gagal memperbarui terakhir_aktif %s", sesi.pk)

    return {
        "sukses": True,
        "data": {
            "tipe": str(keputusan.tipe),
            "jawaban": keputusan.jawaban,
            "skor": round(keputusan.skor, 4),
            "answer_id": keputusan.faq_id,
            "sumber": (keputusan.sumber_url or keputusan.sumber_label) or None,
            "terakhir_diverifikasi": keputusan.terakhir_diverifikasi,
            "kategori": keputusan.kategori,
            "matched": keputusan.matched,
            "kandidat": keputusan.kandidat,
            "session_id": sesi.pk if sesi else None,
            "log_id": log_id,
            "index_version": versi,
            "latency_ms": latency,
        },
    }


# --- POST /v1/chat/session -----------------------------------------------

@chat.post("/session", response=Envelope[SesiData],
           summary="Mulai sesi: nama lengkap + jenis kelamin")
def mulai_sesi(request, payload: SesiRequest):
    """Gerbang sebelum camaba boleh bertanya.

    Frontend memanggil ini SEKALI, menyimpan `session_id` ke localStorage,
    lalu menyertakannya di setiap /query dan /history berikutnya. Yang
    dikumpulkan sengaja minimal — tidak ada NIK, email, atau nomor telepon,
    supaya kebocoran log tidak berubah menjadi kebocoran data pribadi.
    """
    if lewat_batas(request):
        return _tolak_karena_ramai(request)

    from faq.models import PengaturanSapaan
    from percakapan.models import Sesi

    nama = " ".join(payload.nama_lengkap.split())[:120]
    if len(nama) < 2:
        return api.create_response(
            request,
            {"sukses": False, "data": None,
             "pesan": "Nama lengkap tidak boleh kosong."},
            status=422)

    # Email opsional: kosong tetap diterima, tapi kalau diisi harus benar —
    # alamat ngawur di kolom ini membuat panitia mengira camaba bisa dihubungi.
    email = (payload.email or "").strip()[:254]
    if email:
        try:
            validate_email(email)
        except ValidasiDjango:
            return api.create_response(
                request,
                {"sukses": False, "data": None,
                 "pesan": "Format email tidak valid."},
                status=422)

    sesi = Sesi.objects.create(nama_lengkap=nama,
                               jenis_kelamin=payload.jenis_kelamin,
                               email=email)

    pembuka = PengaturanSapaan.ambil().pembuka(sesi.nama_lengkap, sesi.sapaan)

    return {
        "sukses": True,
        "data": {
            "session_id": sesi.pk,
            "nama_lengkap": sesi.nama_lengkap,
            "jenis_kelamin": sesi.jenis_kelamin,
            "email": sesi.email,
            "sapaan": sesi.sapaan,
            "dibuat": sesi.dibuat,
            # Widget merender ini sebagai gelembung berurutan: sapaan
            # bernama dulu, lalu perkenalan chatbot.
            "pembuka": pembuka,
        },
        # Kalimatnya dirakit dari pengaturan admin, bukan ditulis di sini —
        # panitia mengubah sambutan tiap musim PMB tanpa menyentuh kode.
        # Tetap kalimat pertama saja supaya klien lama tidak ikut berubah.
        "pesan": pembuka[0],
    }


# --- GET /v1/chat/history ------------------------------------------------

@chat.get("/history", response=Envelope[RiwayatData],
          summary="Riwayat pertanyaan dalam satu sesi")
def riwayat(request, session_id: str, limit: int = RIWAYAT_MAKS):
    """Dipanggil saat widget dibuka ulang dengan session_id dari localStorage.

    Mengembalikan pertanyaan LAMA TERLEBIH DAHULU supaya frontend tinggal
    merender berurutan seperti gelembung percakapan.
    """
    if lewat_batas(request):
        return _tolak_karena_ramai(request)

    from faq.models import PengaturanSapaan
    from percakapan.models import ChatLog

    sesi = _ambil_sesi(session_id)
    if sesi is None:
        # 404, bukan 200-kosong: frontend perlu tahu localStorage-nya basi
        # dan harus meminta nama + jenis kelamin lagi.
        return api.create_response(
            request,
            {"sukses": False, "data": None,
             "pesan": "Sesi tidak dikenal atau sudah berakhir. "
                      "Silakan isi nama lengkap dan jenis kelamin lagi."},
            status=404)

    batas = max(1, min(limit, RIWAYAT_MAKS))
    # Ambil N TERBARU lalu balik urutannya — bukan N terlama, supaya sesi
    # panjang tetap menampilkan percakapan yang baru saja terjadi.
    baris = list(ChatLog.objects
                 .filter(session_id=sesi.pk)
                 .order_by("-dibuat")[:batas])
    baris.reverse()

    pembuka = PengaturanSapaan.ambil().pembuka(sesi.nama_lengkap, sesi.sapaan)

    return {
        "sukses": True,
        "data": {
            "session_id": sesi.pk,
            "nama_lengkap": sesi.nama_lengkap,
            "email": sesi.email,
            "jenis_kelamin": sesi.jenis_kelamin,
            "sapaan": sesi.sapaan,
            "pesan_pembuka": pembuka[0],
            "pembuka": pembuka,
            "jumlah": len(baris),
            "riwayat": [{
                "log_id": b.log_id,
                "query": b.query,
                "jawaban": b.jawaban,
                "tipe": b.tipe,
                "answer_id": b.faq_id,
                "dibuat": b.dibuat,
            } for b in baris],
        },
    }


# --- POST /v1/chat/feedback ---------------------------------------------

@chat.post("/feedback", response=Envelope[FeedbackData],
           summary="Kirim 👍/👎 atas sebuah jawaban")
def feedback(request, payload: FeedbackRequest):
    """Sinyal untuk fine-tuning putaran berikutnya."""
    if lewat_batas(request):
        return _tolak_karena_ramai(request)

    from percakapan.models import ChatLog, Feedback

    chatlog = ChatLog.objects.filter(pk=payload.log_id).first()
    if chatlog is None:
        return api.create_response(
            request,
            {"sukses": False, "data": None,
             "pesan": "log_id tidak dikenal."},
            status=404)

    Feedback.objects.update_or_create(
        log=chatlog,
        defaults={"rating": payload.rating,
                  "komentar": payload.komentar[:1000]})

    return {"sukses": True,
            "data": {"log_id": payload.log_id, "rating": payload.rating},
            "pesan": "Terima kasih atas masukan Anda."}


# --- GET /v1/health ------------------------------------------------------

@chat.get("/health", response=Envelope[HealthData], summary="Kesiapan layanan")
def health(request):
    """503 saat model belum siap — dipakai monitoring, bukan camaba."""
    from faq.models import Faq
    from faq.services import engine_siap

    engine = engine_siap()
    siap = engine is not None
    data = {
        "status": "ok" if siap else "degraded",
        "model_siap": siap,
        "index_version": engine.snapshot.versi if siap and engine.snapshot else None,
        "jumlah_vektor": engine.snapshot.jumlah_vektor if siap and engine.snapshot else None,
        "jumlah_faq": Faq.objects.filter(aktif=True).count(),
    }
    return api.create_response(
        request, {"sukses": siap, "data": data,
                  "pesan": None if siap else "Model atau index belum siap."},
        status=200 if siap else 503)


api.add_router("/chat/", chat)
