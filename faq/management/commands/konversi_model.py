"""Konversi metadata model dari format sentence-transformers 5.x ke 3.x.

KENAPA PERLU
------------
Colab memakai sentence-transformers 5.x, sementara mesin dev macOS Intel
terkunci di 3.2.1 (torch tidak bisa melewati 2.2.2 di platform ini). Model
hasil fine-tuning karenanya gagal dimuat dengan galat yang tidak menyebut
penyebabnya:

    ModuleNotFoundError: No module named 'sentence_transformers.base'
    TypeError: Transformer.__init__() got unexpected keyword 'transformer_task'
    TypeError: Pooling.__init__() got unexpected keyword 'embedding_dimension'

BOBOT MODELNYA TIDAK BERUBAH — hanya tiga berkas metadata yang skemanya
berbeda. Perintah ini menulis ulang ketiganya ke format lama.

VPS Ubuntu TIDAK butuh ini: di sana torch/ST bisa versi baru.
"""

import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Format lama (sentence-transformers 3.x).
MODULES_3X = [
    {"idx": 0, "name": "0", "path": "",
     "type": "sentence_transformers.models.Transformer"},
    {"idx": 1, "name": "1", "path": "1_Pooling",
     "type": "sentence_transformers.models.Pooling"},
]
SBERT_CONFIG_3X = {"max_seq_length": 128, "do_lower_case": False}


def _pooling_3x(dim: int) -> dict:
    return {
        "word_embedding_dimension": dim,
        "pooling_mode_cls_token": False,
        "pooling_mode_mean_tokens": True,
        "pooling_mode_max_tokens": False,
        "pooling_mode_mean_sqrt_len_tokens": False,
        "include_prompt": True,
    }


def perlu_konversi(model_dir: Path) -> bool:
    """True bila metadata masih format 5.x."""
    p = model_dir / "modules.json"
    if not p.exists():
        return False
    try:
        isi = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return any("sentence_transformers.base" in m.get("type", "")
               or "sentence_transformer.modules" in m.get("type", "")
               for m in isi)


class Command(BaseCommand):
    help = "Konversi metadata model ST 5.x -> 3.x agar bisa dimuat di dev lokal."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=None,
                            help="Direktori model (default: ARTIFACTS_DIR/model)")
        parser.add_argument("--paksa", action="store_true",
                            help="Konversi walau terdeteksi sudah format lama")

    def handle(self, *args, **opts):
        model_dir = Path(opts["dir"] or Path(settings.ARTIFACTS_DIR) / "model")
        if not model_dir.exists():
            raise CommandError(f"Direktori model tidak ada: {model_dir}")

        if not perlu_konversi(model_dir) and not opts["paksa"]:
            self.stdout.write(self.style.SUCCESS(
                f"✅ {model_dir} sudah format lama — tidak perlu dikonversi."))
            return

        # Dimensi diambil dari config model, bukan ditebak.
        cfg = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        dim = cfg.get("hidden_size") or 384

        cadangan = model_dir.parent / "_backup_metadata_5x"
        cadangan.mkdir(parents=True, exist_ok=True)

        berkas = {
            "modules.json": MODULES_3X,
            "sentence_bert_config.json": SBERT_CONFIG_3X,
            "1_Pooling/config.json": _pooling_3x(dim),
        }

        for nama, isi_baru in berkas.items():
            tujuan = model_dir / nama
            if tujuan.exists():
                simpan = cadangan / nama
                simpan.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(tujuan, simpan)
            tujuan.parent.mkdir(parents=True, exist_ok=True)
            tujuan.write_text(json.dumps(isi_baru, indent=2) + "\n",
                              encoding="utf-8")
            self.stdout.write(f"  ✎ {nama}")

        # config_sentence_transformers.json cukup disederhanakan.
        (model_dir / "config_sentence_transformers.json").write_text(
            json.dumps({
                "__version__": {"sentence_transformers": "3.2.1"},
                "prompts": {}, "default_prompt_name": None,
                "similarity_fn_name": "cosine",
            }, indent=2) + "\n", encoding="utf-8")
        self.stdout.write("  ✎ config_sentence_transformers.json")

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Metadata dikonversi ke format 3.x (dim={dim}).\n"
            f"   Berkas asli disimpan di {cadangan}\n"
            f"   Bobot model TIDAK disentuh."))
        self.stdout.write(
            "\nLangkah berikutnya:\n"
            "  python manage.py reindex")
