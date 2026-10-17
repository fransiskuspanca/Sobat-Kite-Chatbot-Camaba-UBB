# ===========================================================================
# SEL PENGGANTI — pembangkitan data latih dengan sinonim domain
#
# Tempel SETELAH sel sinonim_domain.py, MENGGANTIKAN isi sel yang diawali
# komentar "# 4c. Split train/test DI LEVEL PERTANYAAN".
# Prasyarat: df, CFG, SEED, augment() sudah terdefinisi dari sel sebelumnya.
# ===========================================================================

from sklearn.model_selection import train_test_split

train_ids, test_ids = train_test_split(
    df["id"].tolist(),
    test_size=CFG["test_size"],
    random_state=SEED,
    stratify=df["kategori"] if df["kategori"].value_counts().min() >= 2 else None,
)
train_ids, test_ids = set(train_ids), set(test_ids)

train_pairs, test_pairs = [], []
for _, r in df.iterrows():
    bucket = train_pairs if r["id"] in train_ids else test_pairs

    # (1) Augmentasi permukaan — singkatan, typo, sapaan (seperti semula).
    for v in augment(r["pertanyaan"], n=6, seed=r["id"]):
        bucket.append({"query": v, "gold_id": r["id"], "kategori": r["kategori"]})

    # (2) Augmentasi SINONIM DOMAIN — ini yang mengajarkan model bahwa
    #     "kerja praktek" dan "magang" adalah hal yang sama.
    for v in augment_sinonim(r["pertanyaan"], n=4, seed=r["id"]):
        bucket.append({"query": v, "gold_id": r["id"], "kategori": r["kategori"]})

train_df = pd.DataFrame(train_pairs)
test_df = pd.DataFrame(test_pairs)

print(f"Pertanyaan  : {len(train_ids)} train / {len(test_ids)} test")
print(f"Varian query: {len(train_df)} train / {len(test_df)} test")
print(f"Corpus index: {len(df)} (SELURUH pertanyaan — index tidak pernah di-split)")


# ---------------------------------------------------------------------------
# Pasangan sinonim GLOBAL sebagai data latih tambahan.
#
# Tidak terikat FAQ mana pun: mengajarkan relasi sinonimnya sendiri, supaya
# model menggeneralisasi ke parafrase yang belum pernah dilihat — bukan
# sekadar menghafal pertanyaan yang ada.
# ---------------------------------------------------------------------------
from datasets import Dataset

pasangan_global = pasangan_sinonim_global()
print(f"Pasangan sinonim global: {len(pasangan_global)}")

# Dataset utama: (query camaba, pertanyaan kanonik) — MultipleNegativesRankingLoss
peta_kanonik = dict(zip(df["id"], df["pertanyaan"]))
rows = [{"anchor": r["query"], "positive": peta_kanonik[r["gold_id"]]}
        for _, r in train_df.iterrows()]

# Tambahkan pasangan sinonim sebagai contoh kontras.
rows += [{"anchor": a, "positive": b} for a, b in pasangan_global]

train_dataset = Dataset.from_list(rows)
print(f"Total pasangan latih: {len(train_dataset)}")
