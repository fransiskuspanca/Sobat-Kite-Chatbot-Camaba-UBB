"""Sediakan artifacts/model/ untuk pengujian lokal.

Mengunduh model DASAR dari HuggingFace lalu menyambungkannya ke
artifacts/model/ lewat symlink — bukan menyalin, karena salinan kedua
memakan ~465 MB dan disk laptop dev sedang sempit.

⚠️  Ini BUKAN model produksi. Model produksi adalah hasil fine-tuning dari
notebook Colab; letakkan di artifacts/model/ menggantikan symlink ini.
"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

MODEL_DASAR = "LazarusNLP/all-indo-e5-small-v4"   # CFG["model_name"] di notebook

# Repo HuggingFace kadang diperbarui ke format sentence-transformers 5.x, yang
# TIDAK bisa dimuat oleh versi 3.x (satu-satunya yang jalan di macOS Intel,
# karena torch terkunci di 2.2.2). Gejalanya:
#   ModuleNotFoundError: No module named 'sentence_transformers.base'
#   TypeError: Transformer.__init__() got an unexpected keyword 'transformer_task'
#   TypeError: Pooling.__init__() got an unexpected keyword 'embedding_dimension'
#
# Bobot modelnya sendiri tidak berubah — hanya berkas metadata. Ketiga berkas
# di bawah ditulis ulang ke format lama bila versi ST terpasang < 5.
FORMAT_LAMA = {
    "modules.json": [
        {"idx": 0, "name": "0", "path": "",
         "type": "sentence_transformers.models.Transformer"},
        {"idx": 1, "name": "1", "path": "1_Pooling",
         "type": "sentence_transformers.models.Pooling"},
    ],
    "sentence_bert_config.json": {"max_seq_length": 128, "do_lower_case": False},
    "1_Pooling/config.json": {
        "word_embedding_dimension": 384,
        "pooling_mode_cls_token": False,
        "pooling_mode_mean_tokens": True,
        "pooling_mode_max_tokens": False,
        "pooling_mode_mean_sqrt_len_tokens": False,
        "include_prompt": True,
    },
}


class Command(BaseCommand):
    help = "Unduh model dasar & sambungkan ke artifacts/model/ (untuk pengujian)."

    def add_arguments(self, parser):
        parser.add_argument("--model", default=MODEL_DASAR,
                            help=f"Nama model HuggingFace (default {MODEL_DASAR})")
        parser.add_argument("--salin", action="store_true",
                            help="Salin berkas, bukan symlink (butuh ~465 MB)")

    def handle(self, *args, **opts):
        tujuan = Path(settings.ARTIFACTS_DIR) / "model"

        if tujuan.exists() and not tujuan.is_symlink():
            self.stdout.write(self.style.WARNING(
                f"{tujuan} sudah ada dan bukan symlink — dibiarkan apa adanya. "
                "Hapus manual bila ingin menggantinya."))
            return

        self.stdout.write(f"Mengunduh {opts['model']} … "
                          "(sekali saja, lalu dipakai dari cache)")
        try:
            import torch
            from sentence_transformers import SentenceTransformer
            torch.set_num_threads(1)
            model = SentenceTransformer(opts["model"], device="cpu")
        except Exception as e:
            raise CommandError(f"Gagal mengunduh model: {e}")

        dim = model.get_sentence_embedding_dimension()

        if opts["salin"]:
            if tujuan.is_symlink():
                tujuan.unlink()
            model.save(str(tujuan))
            self.stdout.write(self.style.SUCCESS(f"✅ Model disalin ke {tujuan}"))
        else:
            # Cari snapshot lengkap di cache HuggingFace.
            from huggingface_hub import snapshot_download
            snap = Path(snapshot_download(opts["model"]))
            if not (snap / "model.safetensors").exists() and \
               not (snap / "pytorch_model.bin").exists():
                raise CommandError(
                    f"Snapshot di {snap} tidak berisi bobot model. "
                    "Coba ulangi, atau pakai --salin.")
            if tujuan.is_symlink() or tujuan.exists():
                tujuan.unlink()
            tujuan.parent.mkdir(parents=True, exist_ok=True)
            tujuan.symlink_to(snap)
            self.stdout.write(self.style.SUCCESS(
                f"✅ {tujuan} → {snap}  (symlink, tanpa salinan kedua)"))

        self.stdout.write(f"   dimensi embedding: {dim}")
        self.stdout.write(self.style.WARNING(
            "\n⚠️  Ini model DASAR, bukan hasil fine-tuning. Acc@1 akan rendah "
            "dan regression gate akan menolak index — itu perilaku yang benar.\n"
            "   Ganti artifacts/model/ dengan artefak Colab sebelum go-live."))
