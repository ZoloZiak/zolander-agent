#!/usr/bin/env python3
"""zol_mem_text.py — Zolander pamat cez HyperspaceDB server-side embedding (faza 2).

Rozdiel oproti zol_mem.py: embedder ZIJE NA SERVERE (ONNX YARlabs/v5_Embedding_0.5B,
geometry lorentz 129D). Python strana NEPOTREBUJE torch/transformers — len grpcio.
RPC: InsertText (server embedne text sam) -> SearchText (server embedne query sam).
Schema pamati je kompatibilna so zol_mem (kind/layer/salience/confidence v metadata).

Pouzitie:
  python toolkit/zol_mem_text.py init          # vytvor kolekciu zol_mem (lorentz, 129D)
  python toolkit/zol_mem_text.py remember      # stdin JSON {text, kind, layer, confidence, [source, project]}
  python toolkit/zol_mem_text.py recall        # stdin JSON {query, [topk, kind, layer]}
  python toolkit/zol_mem_text.py list [--topk N]
  python toolkit/zol_mem_text.py health

Env: HYPERSPACE_HOST (default localhost:50051), HYPERSPACE_API_KEY,
HS_SDK_PATH (default <home>/hyperspace-db/sdks/python), ZOLANDER_ROOT.
Vystup JSON na stdout. Exit 0 = OK.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

# stdout UTF-8: nadriadený číta encoding="utf-8"; bez reconfigure tento
# proces píše locale (cp1250) a reader-thread rodiča padá na nevalidných bajtoch.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- konstanty (anti-dup: dimenstion/metric su tu, lebo tu sa VZDYTEE pouzivaju) ---
COLLECTION = "zol_mem"
LORENTZ_DIM = 129  # spatial 128 + 1 casova zlozka
METRIC = "lorentz"
KINDS = {"episodic", "semantic", "procedural", "identity"}
LAYERS = {"L0", "L1", "L2", "L3"}


def rpc_call(fn, **kwargs):
    """Zavola SDK funkciu s chytenym stdout: SDK RPC chyby len PRINTNE na
    stdout a vrati fallback ([], False, {}) — beziace JSON vystupu by inak
    klamal 'ok: true' pri padnutom servere. Tu to zachytim a ok:false je
    poctivy stav. Vracia (result, rpc_error|None)."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(**(kwargs or {}))
    err = buf.getvalue()
    if "RPC Error" not in err:
        return result, None
    short = ""
    for line in err.splitlines():
        s = line.strip()
        if s.startswith("status = "):
            short += s.replace("status = ", "status ") + " "
        elif s.startswith("details = "):
            short += s
            break
    return result, (short.strip().rstrip(",") or err.strip().splitlines()[0])


def sdk_path() -> str:
    return os.environ.get("HS_SDK_PATH") or os.path.expanduser(r"~\hyperspace-db\sdks\python")


def make_client():
    if not os.path.isdir(sdk_path()):
        raise RuntimeError(
            f"HyperspaceDB SDK nenajdeny: {sdk_path()}. Nastav HS_SDK_PATH alebo naklonuj repo."
        )
    sys.path.insert(0, sdk_path())
    from hyperspace.client import HyperspaceClient  # noqa: E402

    host = os.environ.get("HYPERSPACE_HOST", "localhost:50051")
    api_key = os.environ.get("HYPERSPACE_API_KEY") or "I_LOVE_HYPERSPACEDB"
    return HyperspaceClient(host=host, api_key=api_key)


def next_id_path() -> str:
    root = os.environ.get("ZOLANDER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.join(root, "state"), exist_ok=True)
    return os.path.join(root, "state", "mem_next_id.txt")


def next_id() -> int:
    p = next_id_path()
    current = 1
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                current = max(int(f.read().strip() or "0") + 1, 1)
        except (OSError, ValueError):
            current = 1
    with open(p, "w", encoding="utf-8") as f:
        f.write(str(current))
    return current


def read_stdin_json() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        raise RuntimeError("ocakavam JSON na stdin — prazdny vstup")
    return json.loads(raw)


def cmd_init(_: argparse.Namespace) -> dict:
    client = make_client()
    ok, rpc_err = rpc_call(client.create_collection, name=COLLECTION, dimension=LORENTZ_DIM, metric=METRIC)
    if rpc_err:
        return {"ok": False, "mode": "init", "error": "RPC chyba: " + rpc_err, "note": "server nebezi? pozri OPENCODE_PORT.md (WSL sluzba)"}
    return {
        "ok": bool(ok),
        "mode": "init",
        "collection": COLLECTION,
        "engine": "server-side YAR v5 (lorentz 129D, hyperspace v4)",
        "note": "server musi mat HS_EMBED_LORENTZ_PROVIDER=huggingface (YARlabs/v5_Embedding_0.5B)",
    }


def cmd_remember(_: argparse.Namespace) -> dict:
    obj = read_stdin_json()
    text = str(obj.get("text", "")).strip()
    if not text:
        raise RuntimeError("text nesmie byt prazdny")
    kind = obj.get("kind", "episodic")
    layer = obj.get("layer", "L0")
    conf = float(obj.get("confidence", 0.6))
    if kind not in KINDS:
        raise RuntimeError(f"kind musi byt z {sorted(KINDS)}")
    if layer not in LAYERS:
        raise RuntimeError(f"layer musi byt z {sorted(LAYERS)}")
    if not 0.0 <= conf <= 1.0:
        raise RuntimeError("confidence musi byt 0..1")
    client = make_client()
    eid = next_id()
    metadata = {
        "kind": kind,
        "layer": layer,
        "salience": f"{conf * 0.8:.3f}",
        "confidence": f"{conf:.3f}",
        "source": str(obj.get("source", "session")),
        "project": str(obj.get("project", "")),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "engine": "lorentz-server-v1",
        # A2A Ed25519 podpis (nepovinny — bez orchestratora je zapis nepodpisany)
        "sig": str(obj.get("sig") or ""),
        "sig_from_fp": str(obj.get("from_fp") or ""),
        "sig_ts": str(obj.get("ts_signed") or ""),
        # Ascend L1 (zol_ascend): viazanosť konceptu na L0 členov.
        "members": str(obj.get("members") or ""),
        "members_hash": str(obj.get("members_hash") or ""),
        # Server-side InsertText NESTORUJE text (embedne a zahodi, pozri
        # crates/hyperspace-server/src/server.rs InsertText handler) — plaintext
        # preto nesie metadata a recall ho vrati z nej.
        "text": text[:4000],
    }
    ok, rpc_err = rpc_call(client.insert_text, id=eid, text=text, metadata=metadata, collection=COLLECTION)
    if rpc_err:
        return {"ok": False, "mode": "remember", "id": eid, "error": "RPC chyba: " + rpc_err}
    return {"ok": bool(ok), "mode": "remember", "id": eid, "engine": "lorentz-server-v1"}


def cmd_recall(_: argparse.Namespace) -> dict:
    obj = read_stdin_json()
    query = str(obj.get("query", "")).strip()
    if not query:
        raise RuntimeError("query nesmie byt prazdna")
    topk = int(obj.get("topk", 5))
    client = make_client()
    filt = {}
    if obj.get("kind"):
        filt["kind"] = str(obj["kind"])
    if obj.get("layer"):
        filt["layer"] = str(obj["layer"])
    hits, rpc_err = rpc_call(
        client.search_text,
        text=query,
        top_k=topk,
        filter=filt or None,
        collection=COLLECTION,
    )
    if rpc_err:
        return {"ok": False, "mode": "recall", "engine": "lorentz-server-v1", "hits": [], "error": "RPC chyba: " + rpc_err}
    # SearchText vracia len id/distance/metadata — plaintext dohladam cez get_points.
    ids = [h.get("id") for h in hits if isinstance(h.get("id"), int)]
    if ids:
        points, rp_err2 = rpc_call(client.get_points, ids=ids, collection=COLLECTION)
        if not rp_err2 and isinstance(points, list):
            by_id = {p.get("id"): p for p in points if isinstance(p, dict)}
            for h in hits:
                p = by_id.get(h.get("id")) or {}
                doc = p.get("document") or p.get("text") or p.get("payload_text") or ""
                if isinstance(doc, bytes):
                    doc = doc.decode("utf-8", "replace")
                if doc:
                    h["document"] = doc
    for h in hits:
        md = h.get("metadata") or {}
        h["kind"] = md.get("kind")
        h["layer"] = md.get("layer")
        h["confidence"] = md.get("confidence")
        h["salience"] = md.get("salience")
        h["ts"] = md.get("ts")
        h["document"] = md.get("text") or ""
    return {"ok": True, "mode": "recall", "engine": "lorentz-server-v1", "hits": hits}


def cmd_list(args: argparse.Namespace) -> dict:
    client = make_client()
    stats, rpc_err = rpc_call(client.get_collection_stats, name=COLLECTION)
    if rpc_err:
        return {"ok": False, "mode": "list", "error": "RPC chyba: " + rpc_err}
    return {"ok": True, "mode": "list", "stats": stats, "note": "list nie je v tomto rezime (pozri stats)"}


def cmd_health(_: argparse.Namespace) -> dict:
    client = make_client()
    stats, rpc_err = rpc_call(client.get_collection_stats, name=COLLECTION)
    if rpc_err:
        return {
            "ok": False,
            "error": "RPC nedostupny: " + rpc_err,
            "note": "server nebezi? spusti ho vo WSL (pozri OPENCODE_PORT.md)",
        }
    return {"ok": True, "collection": COLLECTION, "server": os.environ.get("HYPERSPACE_HOST", "localhost:50051"), "stats": stats}


def main() -> None:
    p = argparse.ArgumentParser(description="Zolander HyperspaceDB text-embedding pamat (faza 2)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("remember").set_defaults(func=cmd_remember)
    sub.add_parser("recall").set_defaults(func=cmd_recall)
    l = sub.add_parser("list")
    l.add_argument("--topk", type=int, default=10)
    l.set_defaults(func=cmd_list)
    sub.add_parser("health").set_defaults(func=cmd_health)
    args = p.parse_args()
    print(json.dumps(args.func(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
