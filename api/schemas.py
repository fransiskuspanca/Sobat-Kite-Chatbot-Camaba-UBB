"""Skema Pydantic — bentuk response API.

Prinsip #2: setiap jawaban dapat diaudit. Response WAJIB menyertakan
`answer_id`, `sumber`, dan `terakhir_diverifikasi` supaya panitia bisa
menelusuri dari mana sebuah jawaban berasal.

Bentuk envelope sengaja seragam untuk semua endpoint agar frontend tidak
perlu menebak-nebak struktur.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from ninja import Schema
from pydantic import Field

T = TypeVar("T")

# Batas panjang query — sejalan dengan client_max_body_size 16k di Nginx.
PANJANG_QUERY_MAKS = 500

# Riwayat dibatasi supaya satu sesi panjang tidak menarik ribuan baris
# sekaligus saat widget dibuka ulang.
RIWAYAT_MAKS = 50


class Envelope(Schema, Generic[T]):
    """Pembungkus seragam: {"sukses": bool, "data": ..., "pesan": ...}."""
    sukses: bool = True
    data: T | None = None
    pesan: str | None = None


# --- /v1/chat/query ------------------------------------------------------

class ChatQueryRequest(Schema):
    query: str = Field(..., min_length=1, max_length=PANJANG_QUERY_MAKS,
                       description="Pertanyaan camaba")
    session_id: str | None = Field(
        None, max_length=64,
        description="Diperoleh dari POST /v1/chat/session dan disimpan "
                    "frontend di localStorage. Tidak dipakai untuk "
                    "autentikasi — hanya pengelompokan riwayat.")


class KandidatOut(Schema):
    """Kandidat jawaban lain — dipakai saat tipe='klarifikasi'."""
    id: int
    pertanyaan: str
    skor: float


class ChatQueryData(Schema):
    tipe: Literal["jawaban", "klarifikasi", "eskalasi", "fallback",
                  "sapaan", "identitas", "kosong"]
    jawaban: str
    skor: float

    # --- jejak audit (prinsip #2) ---
    answer_id: int | None = None
    sumber: str | None = None
    terakhir_diverifikasi: date | None = None

    kategori: str | None = None
    matched: str | None = None
    kandidat: list[KandidatOut] = []

    # --- sesi ---
    # Dikembalikan supaya frontend bisa menyimpannya ke localStorage tanpa
    # menebak-nebak; nilainya sama dengan yang dikirim di request.
    session_id: str | None = None

    # --- telemetri ---
    log_id: str
    index_version: int | None = None
    latency_ms: int


# --- /v1/chat/session ----------------------------------------------------

class SesiRequest(Schema):
    """Camaba WAJIB mengisi ini sebelum boleh bertanya."""
    nama_lengkap: str = Field(..., min_length=2, max_length=120,
                              description="Nama lengkap camaba")
    jenis_kelamin: Literal["L", "P"] = Field(
        ..., description="L = Laki-laki, P = Perempuan")
    email: str | None = Field(
        None, max_length=254,
        description="Opsional — dipakai panitia untuk menghubungi balik "
                    "camaba yang pertanyaannya belum terjawab.")


class SesiData(Schema):
    session_id: str
    nama_lengkap: str
    jenis_kelamin: Literal["L", "P"]
    email: str = ""
    sapaan: str
    dibuat: datetime
    # Gelembung pembuka, berurutan: sapaan bernama lalu perkenalan chatbot.
    # Envelope.pesan tetap berisi kalimat pertama demi klien lama.
    pembuka: list[str] = []


# --- GET /v1/chat/history ------------------------------------------------

class RiwayatItem(Schema):
    """Satu putaran tanya-jawab, siap dirender ulang oleh widget."""
    log_id: str
    query: str
    jawaban: str
    tipe: str
    answer_id: int | None = None
    dibuat: datetime


class RiwayatData(Schema):
    session_id: str
    nama_lengkap: str
    jenis_kelamin: Literal["L", "P"]
    email: str = ""
    sapaan: str
    # Widget menampilkan sambutan ini saat riwayat masih kosong; dikirim dari
    # server supaya kalimatnya sama dengan yang dipakai /session.
    pesan_pembuka: str = ""
    # Bentuk banyak-gelembung dari kalimat yang sama; pesan_pembuka
    # dipertahankan (= pembuka[0]) supaya klien lama tidak ikut berubah.
    pembuka: list[str] = []
    jumlah: int
    riwayat: list[RiwayatItem] = []


# --- /v1/chat/feedback ---------------------------------------------------

class FeedbackRequest(Schema):
    log_id: str = Field(..., max_length=40)
    rating: Literal["up", "down"]
    komentar: str = Field("", max_length=1000)


class FeedbackData(Schema):
    log_id: str
    rating: str


# --- /v1/health ----------------------------------------------------------

class HealthData(Schema):
    status: Literal["ok", "degraded"]
    model_siap: bool
    index_version: int | None = None
    jumlah_vektor: int | None = None
    jumlah_faq: int | None = None
