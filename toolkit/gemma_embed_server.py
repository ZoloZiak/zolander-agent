#!/usr/bin/env python3
"""gemma_embed_server.py — perzistentny EmbeddingGemma embed daemon (768D cosine).

Preco daemon: model load ~4s. Volat subprocess pri kazdom recall = +4s/dotaz = neunosne.
Daemon drzi model v pamati a odpoveda na HTTP embed requesty za ~ms.
Vzor ako hs.mjs — samostatny proces, lazy-start cez ensure skript.

Cross-platform backend (auto-detect, v tomto poradi):
  1. mlx_embeddings  — Apple Silicon GPU (rychle, 6bit kvant). Autorov Mac.
  2. sentence-transformers / torch — CPU aj CUDA, bezi vsade (Linux kamos).
Oba davaju ten isty 768D L2-normalizovany vektor pre ten isty text (rovnaky
model rodiny EmbeddingGemma, rovnake asymetricke prefixy, finalna L2 norma),
takze kolekcia zol_mem_gemma je prenosna medzi strojmi.

Port 8901 (volny, over pred pouzitim).
Endpoint:  POST /embed   telo {"texts": ["...", ...], "mode": "query"|"document"}
                         -> {"vectors": [[768f], ...]}
           GET  /health  -> {"status":"ok","model":...,"dim":768,"backend":...}
Vektory su L2-normalizovane (cosine-ready).
"""
import os
import sys
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Offline iba ak existuje lokalna cache; inak povol prvy HF download.
if os.environ.get("GEMMA_OFFLINE") == "1":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# MLX pouziva 6bit kvant z mlx-community; torch/ST cesta pouziva Google canonical.
# Prepis cez GEMMA_MLX_MODEL / GEMMA_MODEL ak tvoj stroj ma iny mirror.
MLX_MODEL = os.environ.get("GEMMA_MLX_MODEL", "mlx-community/embeddinggemma-300m-6bit")
ST_MODEL = os.environ.get("GEMMA_MODEL", "google/embeddinggemma-300m")
PORT = int(os.environ.get("GEMMA_EMBED_PORT", "8901"))

# EmbeddingGemma je ASYMETRICKA — oficialne prompt prefixy (Google model card).
# Bez nich je retrieval rozbity (overene: q.doc < q.noise). Query a dokument
# MUSIA ist s roznym prefixom. mode="query"|"document" v /embed tele.
QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "

_state = {"backend": None, "name": None, "mlx_model": None, "mlx_tok": None, "st": None}


def _load():
    """Lazy-load: skus MLX (Apple), inac spadni na sentence-transformers (vsade)."""
    if _state["backend"] is not None:
        return
    force = os.environ.get("GEMMA_BACKEND", "").lower()  # "mlx"|"st"|"" (auto)
    if force != "st":
        try:
            from mlx_embeddings import load
            m, t = load(MLX_MODEL)
            _state.update(backend="mlx", name=MLX_MODEL, mlx_model=m, mlx_tok=t)
            return
        except Exception as e:
            if force == "mlx":
                raise
            print(f"[gemma] MLX nedostupne ({e!r}), skusam sentence-transformers",
                  file=sys.stderr, flush=True)
    from sentence_transformers import SentenceTransformer
    _state.update(backend="st", name=ST_MODEL,
                  st=SentenceTransformer(ST_MODEL))


def _l2(mat):
    """L2-normalizuj kazdy riadok (cosine-ready). Idempotentne pre uz-normalizovane."""
    import numpy as np
    a = np.asarray(mat, dtype="float32")
    n = np.linalg.norm(a, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return (a / n).tolist()


def embed(texts, mode="document"):
    import numpy as np
    _load()
    prefix = QUERY_PREFIX if mode == "query" else DOC_PREFIX
    ptexts = [prefix + t for t in texts]

    if _state["backend"] == "mlx":
        model, tok = _state["mlx_model"], _state["mlx_tok"]
        inner = getattr(tok, "_tokenizer", tok)
        out = []
        B = 16
        for i in range(0, len(ptexts), B):
            chunk = ptexts[i:i + B]
            # padding='max_length' + fixna dlzka = DETERMINISTICKY vektor nezavisly od davky
            enc = inner(chunk, return_tensors="mlx", padding="max_length",
                        truncation=True, max_length=256)
            r = model(enc["input_ids"], attention_mask=enc["attention_mask"])
            out.append(np.array(r.text_embeds, dtype="float32"))
        return _l2(np.vstack(out))

    # sentence-transformers / torch (CPU alebo CUDA)
    vecs = _state["st"].encode(ptexts, batch_size=16, convert_to_numpy=True,
                               truncation=True, normalize_embeddings=False)
    return _l2(vecs)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # ticho

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "model": _state["name"],
                             "dim": 768, "backend": _state["backend"]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/embed":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or "{}")
            texts = data.get("texts") or []
            mode = data.get("mode", "document")
            if not isinstance(texts, list) or not texts:
                self._send(400, {"error": "texts must be non-empty list"})
                return
            self._send(200, {"vectors": embed(texts, mode=mode)})
        except Exception as e:
            self._send(500, {"error": repr(e)})


def main():
    _load()  # warm-up pri starte
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"gemma_embed_server ready on :{PORT} model={_state['name']} "
          f"backend={_state['backend']}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
