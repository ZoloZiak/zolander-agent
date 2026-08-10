#!/usr/bin/env python3
"""embed_yar.py — natívny 129D Lorentz embedder (YARlabs/v5_Embedding_0.5B).

NAHRÁDZA starý embed.py (EmbeddingGemma 768 cosine + toy to_lorentz).
Model dáva PRIAMO 129D Lorentz vektor na hyperboloide (<x,x>_L = -1):
  text -> Qwen2 transformer -> last-token pooling -> LorentzMRLHead -> expmap0
Polomer (hĺbka abstrakcie) je NAUČENÝ modelom (norma vektora v hlave),
NIE nalepený tabuľkou LAYER_R. To je jadro opravy cargo-cultu (PLAN §11/§14).

Použitie (stdin JSONL {id, text} -> stdout JSONL {id, vector[129]}):
  VPY=/Users/__USER__/zolander/.venv-yar/bin/python
  echo '{"id":1,"text":"..."}' | $VPY embed_yar.py
  $VPY embed_yar.py < atoms.jsonl > vectors.jsonl

Prostredie (overené PLAN §14):
  - venv .venv-yar: torch 2.13 + transformers PINNUTÝ 5.0.0 (>5.0 rozbije masking)
  - model lokálne v ~/models/yar_v5_embedding (Apache-2.0), NESŤAHUJE z HF
  - device CPU (MPS má bf16 matmul bug), dtype float32 (Lorentz hlava kastuje na fp32)
  - target_dim=128 -> výstup 129 (128 priestor + 1 časová x0)
"""
import os, sys, json, time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from transformers import AutoTokenizer, AutoModel

MODEL_ID = os.environ.get("YAR_MODEL", "/Users/__USER__/models/yar_v5_embedding")
TARGET_DIM = int(os.environ.get("YAR_TARGET_DIM", "128"))  # -> 129D Lorentz
BATCH = int(os.environ.get("YAR_BATCH", "16"))
DEVICE = "cpu"  # MPS bf16 matmul bug; 0.5B na CPU je dostatočne rýchle

_MODEL = None
_TOK = None


def get_model():
    global _MODEL, _TOK
    if _MODEL is None:
        _TOK = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
        _MODEL = AutoModel.from_pretrained(
            MODEL_ID, trust_remote_code=True, dtype=torch.float32
        )
        _MODEL.eval().to(DEVICE)
    return _MODEL, _TOK


def embed_batch(texts):
    """List[str] -> List[List[float]] (každý 129D Lorentz)."""
    model, tok = get_model()
    enc = tok(texts, padding=True, truncation=True, max_length=512,
              return_tensors="pt").to(DEVICE)
    with torch.no_grad():
        vecs = model(**enc, target_dim=TARGET_DIM)
    return [_reproject(v) for v in vecs.tolist()]


def _reproject(v):
    """Re-projektuj na Lorentz hyperboloid tak, aby -x0^2+|x|^2 = -1 platilo
    PRESNE. Model dava fp32 s malou chybou (~1e-6) a hs.mjs validuje prisne
    (ERR 'not on unit hyperboloid'). x0 je zavisla suradnica: x0 = sqrt(1+|x|^2).
    Priestorovu cast (v[1:]) berieme ako pravdu, x0 dopocitame."""
    import math
    space = v[1:]
    s2 = sum(c * c for c in space)
    x0 = math.sqrt(1.0 + s2)
    return [x0] + space


def embed_one(text):
    """Pohodlný single-text helper pre import z iných skriptov."""
    return embed_batch([text])[0]


def embed_many(texts):
    """List[str] -> List[129D Lorentz vektor]. Import helper pre ascend/patterns/lens.
    Rešpektuje BATCH. Prázdny zoznam -> []."""
    out = []
    for i in range(0, len(texts), BATCH):
        out.extend(embed_batch(texts[i:i + BATCH]))
    return out


def lorentz_dist(a, b):
    """Natívna Lorentzova (hyperboloidová) vzdialenosť dvoch 129D bodov.
    d = arccosh(-<a,b>_L), kde <a,b>_L = -a0*b0 + suma(ai*bi).
    Menšie = bližšie. Nahrádza cosine pri clusteringu (sme v hyperbolickom
    priestore, cosine tu nedáva zmysel). Robustné voči fp: -<a,b> >= 1."""
    import math
    mink = -a[0] * b[0] + sum(x * y for x, y in zip(a[1:], b[1:]))
    val = -mink
    if val < 1.0:
        val = 1.0  # fp guard: arccosh definované len pre >=1
    elif val > 1e6:
        val = 1e6  # fp guard (red-team #3): pri obrom r stráca acosh presnosť; nad
                   # ~1e6 (acosh≈14.5) su body uz nerozlisitelne "velmi daleko", clip
                   # zreze zaokrуhlovaci sum bez straty uzitocnej informacie.
    return math.acosh(val)


def main():
    items = []
    for line in sys.stdin:
        line = line.strip()
        if line:
            items.append(json.loads(line))
    if not items:
        return
    t0 = time.time()
    n = 0
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        vecs = embed_batch([c["text"] for c in chunk])
        for c, v in zip(chunk, vecs):
            print(json.dumps({"id": c["id"], "vector": v}))
        n += len(chunk)
        print(f"[embed_yar] {n}/{len(items)} ({time.time()-t0:.1f}s)", file=sys.stderr)


if __name__ == "__main__":
    main()
