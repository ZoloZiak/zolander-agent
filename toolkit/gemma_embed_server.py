#!/usr/bin/env python3
"""gemma_embed_server.py — perzistentny EmbeddingGemma embed daemon (768D cosine).

Preco daemon: model load ~4s. Volat subprocess pri kazdom recall = +4s/dotaz = neunosne.
Daemon drzi model v pamati (MLX/GPU) a odpoveda na HTTP embed requesty za ~ms.
Vzor ako agy_bridge/hs.mjs — samostatny proces, lazy-start cez ensure skript.

Bezi POD vMLX uv-tool python (ma mlx_embeddings). Port 8901 (volny, over pred pouzitim).
Endpoint:  POST /embed   telo {"texts": ["...", ...]}  -> {"vectors": [[768f], ...]}
           GET  /health  -> {"status":"ok","model":...,"dim":768}
Vektory su L2-normalizovane (cosine-ready).
"""
import os
import sys
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

MODEL = "mlx-community/embeddinggemma-300m-6bit"
PORT = int(os.environ.get("GEMMA_EMBED_PORT", "8901"))

# EmbeddingGemma je ASYMETRICKA — oficialne prompt prefixy (Google model card).
# Bez nich je retrieval rozbity (overene: q.doc < q.noise). Query a dokument
# MUSIA ist s roznym prefixom. mode="query"|"document" v /embed tele.
QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "title: none | text: "

_state = {"model": None, "tok": None}


def _load():
    if _state["model"] is None:
        from mlx_embeddings import load
        m, t = load(MODEL)
        _state["model"], _state["tok"] = m, t
    return _state["model"], _state["tok"]


def embed(texts, mode="document"):
    import numpy as np
    model, tok = _load()
    inner = getattr(tok, "_tokenizer", tok)
    prefix = QUERY_PREFIX if mode == "query" else DOC_PREFIX
    ptexts = [prefix + t for t in texts]
    out = []
    B = 16
    for i in range(0, len(ptexts), B):
        chunk = ptexts[i:i + B]
        # padding='max_length' + fixna dlzka = DETERMINISTICKY vektor nezavisly od davky
        enc = inner(chunk, return_tensors="mlx", padding="max_length",
                    truncation=True, max_length=256)
        r = model(enc["input_ids"], attention_mask=enc["attention_mask"])
        out.append(np.array(r.text_embeds, dtype="float32"))
    return np.vstack(out).tolist()


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
            self._send(200, {"status": "ok", "model": MODEL, "dim": 768})
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
    print(f"gemma_embed_server ready on :{PORT} model={MODEL}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
