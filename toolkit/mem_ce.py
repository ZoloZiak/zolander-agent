#!/usr/bin/env python3
"""mem_ce.py — lokalny multilingvalny cross-encoder reranker (SK/PL/EN).

Model cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 (XLM-R, multilingval vratane PL/SK).
Beztak lokalny (ziadny leak), ciste transformers (venv-yar ma torch+transformers).
Vola sa NA KANDIDATOCH z hybrid recallu (top-K), preusporiada podla relevancie query.
Lazy-load modelu (singleton), fail-open (chyba -> povodne poradie).

Pouzitie:
  from mem_ce import rerank_ce
  order = rerank_ce(query, [{"id":.., "text":..}, ...])   # vrat list id preusporiadane
"""
import os

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
_state = {"tok": None, "model": None}


def _lazy():
    if _state["model"] is None:
        import torch  # noqa
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        _state["tok"] = AutoTokenizer.from_pretrained(MODEL)
        m = AutoModelForSequenceClassification.from_pretrained(MODEL)
        m.eval()
        _state["model"] = m
    return _state["tok"], _state["model"]


def score(query, texts, max_length=256):
    """Vrat list float skore (vyssie = relevantnejsie) pre (query, text) pary."""
    import torch
    tok, model = _lazy()
    with torch.no_grad():
        enc = tok([query] * len(texts), list(texts), padding=True, truncation=True,
                  return_tensors="pt", max_length=max_length)
        logits = model(**enc).logits.squeeze(-1)
        if logits.ndim == 0:
            logits = logits.unsqueeze(0)
        return [float(x) for x in logits]


def rerank_ce(query, candidates, max_ids=None):
    """candidates: list dict s 'id','text'. Vrat list id preusporiadane. Fail-open."""
    orig = [c["id"] for c in candidates]
    if not candidates:
        return orig
    try:
        sc = score(query, [c.get("text", "") for c in candidates])
        order = [c["id"] for c, _ in sorted(zip(candidates, sc), key=lambda z: -z[1])]
        return order[:max_ids] if max_ids else order
    except Exception:
        return orig


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "hladam izbu blizko roboty"
    cands = [
        {"id": 1, "text": "IZBY na prenajom projekt zolander-rooms pri praci"},
        {"id": 2, "text": "HyperspaceDB kontajner na porte 50051"},
        {"id": 3, "text": "izby pokoj prenajom lokalita byt"},
    ]
    print(rerank_ce(q, cands))
