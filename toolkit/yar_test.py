#!/usr/bin/env python3
"""yar_test.py — IZOLOVANY test YARlabs/v5_Embedding_0.5B pred nasadenim.

Overuje 3 veci (go/no-go pre cestu B):
  1. model sa nacita a bezi na tomto stroji (MPS ak je, inak CPU)
  2. vystup je 129D Lorentz vektor (target_dim=128 -> 128+1)
  3. SK/PL/EN multilingvalnost: suvisiace vety BLIZKO, nesuvisiace DALEKO
     (meria sa PRAVA Lorentzova vzdialenost, nie cosine)

Spustenie:
  <venv>/bin/python toolkit/yar_test.py

Model sa stiahne z HF do cache pri prvom behu (~2.4GB safetensors vetva),
alebo pouzije lokalnu kopiu ak existuje (WHISPER-style resolution).
"""
import os, sys, time
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from transformers import AutoTokenizer, AutoModel

# local-else-HF: lokalny adresar (offline) ak existuje, inak verejny HF repo.
_local = os.path.expanduser(os.environ.get("YAR_MODEL", "~/models/yar_v5_embedding"))
MODEL_ID = _local if os.path.isdir(_local) else "YARlabs/v5_Embedding_0.5B"
TARGET_DIM = 128  # -> 129D Lorentz vystup


def lorentz_dist(u, v):
    """Prava hyperbolicka vzdialenost medzi dvoma Lorentz vektormi (signatura - + +...)."""
    u0, ux = u[..., 0:1], u[..., 1:]
    v0, vx = v[..., 0:1], v[..., 1:]
    inner = -u0 * v0 + (ux * vx).sum(dim=-1, keepdim=True)
    inner = torch.clamp(inner, max=-1.0)  # acosh definovany len pre >=1
    return torch.acosh(-inner).squeeze(-1)


def main():
    # MPS ma bug s bf16 matmul (Destination/Accumulator datatype mismatch);
    # 0.5B model je na CPU na embedding uplne dostatocny a spolahlivy.
    dev = "cpu"
    print(f"[1] device = {dev}, torch = {torch.__version__}")

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    # float32 cely model: Lorentz hlava interne kastuje na float32, takze bf16
    # vahy by robili dtype mismatch (mat1 Float x mat2 BFloat16). Na CPU je fp32 aj tak nativne.
    model = AutoModel.from_pretrained(MODEL_ID, trust_remote_code=True, dtype=torch.float32)
    model.eval().to(dev)
    print(f"[1] model nacitany za {time.time()-t0:.1f}s")

    # trojice: (SK, PL, EN) suvisiace + jedna nesuvisiaca kotva
    texts = [
        "Zolander je perzistentny AI partak, ktory si pamata napriec sesiami.",   # 0 SK
        "Zolander to trwaly agent AI, ktory pamieta miedzy sesjami.",             # 1 PL (parafraza 0)
        "Zolander is a persistent AI companion that remembers across sessions.",  # 2 EN (parafraza 0)
        "Recept na gulas: cibulu opraz na masti a pridaj papriku.",               # 3 SK nesuvisiace
    ]

    enc = tok(texts, padding=True, truncation=True, max_length=512, return_tensors="pt").to(dev)
    with torch.no_grad():
        vecs = model(**enc, target_dim=TARGET_DIM)
    print(f"[2] vystup shape = {tuple(vecs.shape)}  (ocakavam [4, {TARGET_DIM+1}])")
    assert vecs.shape[1] == TARGET_DIM + 1, "NIE JE 129D! Lorentz hlava nedava +1"

    # overenie ze su naozaj na hyperboloide: <x,x>_L = -1
    x0, xs = vecs[:, 0], vecs[:, 1:]
    mink = (-x0 * x0 + (xs * xs).sum(dim=-1))
    print(f"[2] Minkowski <x,x>_L = {[round(float(m),3) for m in mink]}  (ocakavam ~ -1.0)")

    print("[3] Lorentzove vzdialenosti od SK vety [0]:")
    labels = ["SK->PL(parafraza)", "SK->EN(parafraza)", "SK->gulas(nesuvis)"]
    d_pl = float(lorentz_dist(vecs[0], vecs[1]))
    d_en = float(lorentz_dist(vecs[0], vecs[2]))
    d_no = float(lorentz_dist(vecs[0], vecs[3]))
    for lab, d in zip(labels, [d_pl, d_en, d_no]):
        print(f"      {lab:22s} = {d:.4f}")

    ok_pl = d_pl < d_no
    ok_en = d_en < d_no
    print()
    print(f"[VERDIKT] PL parafraza blizsie nez nesuvis: {'ANO' if ok_pl else 'NIE'}")
    print(f"[VERDIKT] EN parafraza blizsie nez nesuvis: {'ANO' if ok_en else 'NIE'}")
    if ok_pl and ok_en:
        print("[VERDIKT] ✅ SK/PL/EN multilingvalnost FUNGUJE — cesta B potvrdena naostro")
        return 0
    print("[VERDIKT] ⚠️ multilingvalnost slaba — treba zvazit")
    return 1


if __name__ == "__main__":
    sys.exit(main())
