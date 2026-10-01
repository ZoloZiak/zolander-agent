#!/usr/bin/env python3
"""zol_paths.py — prenositelne rozlisenie ciest pre Zolander toolkit.

Ziaden hardcoded /Users/... layout. Kazda cesta sa najprv vezme z env
(explicitny override), inak sa AUTO-DETEKUJE z rozumnych kandidatov, inak
padne na default. Tak bezi identicky kod:
  - u autora (~/projects/zolander + ~/projects/zolo2.0),
  - u klonujuceho (~/zolander + repo-lokalny hs.mjs vedla tohto suboru).

Import: `from zol_paths import HS, NODE, NODE_ENV, ZROOT, ZOLO2, here`.
"""
import os
import glob
import shutil

HOME = os.path.expanduser("~")
here = os.path.dirname(os.path.abspath(__file__))


def _first_existing(cands, default):
    for c in cands:
        if c and os.path.exists(c):
            return c
    return default


def zolander_root():
    """Korenovy adresar Zolandera (kde su PLAN.md, state/, logs/, denniky/)."""
    return os.environ.get("ZOLANDER_ROOT") or _first_existing(
        [os.path.join(HOME, "projects", "zolander"), os.path.join(HOME, "zolander")],
        os.path.join(HOME, "zolander"),
    )


def zolo2_root():
    """Korenovy adresar zolo2.0 (volitelny — cross-import pri niektorych nastrojoch)."""
    return os.environ.get("ZOLO2_ROOT") or _first_existing(
        [os.path.join(HOME, "projects", "zolo2.0"), os.path.join(HOME, "zolo2.0")],
        os.path.join(HOME, "zolo2.0"),
    )


def hs_mjs():
    """Node SDK most hs.mjs. Priorita: env -> vedla tohto suboru (repo ploche
    toolkit/) -> zolo2.0/toolkit (layout autora)."""
    return os.environ.get("ZOL_HS_MJS") or _first_existing(
        [os.path.join(here, "hs.mjs"), os.path.join(zolo2_root(), "toolkit", "hs.mjs")],
        os.path.join(here, "hs.mjs"),
    )


def node_bin():
    """node binarka: env -> PATH -> zvycajne miesta (launchd ma orezany PATH)."""
    return (
        os.environ.get("ZOL_NODE")
        or shutil.which("node")
        or _first_existing(
            [
                os.path.join(HOME, "Applications", "homebrew", "bin", "node"),
                "/opt/homebrew/bin/node",
                "/usr/local/bin/node",
            ],
            "node",
        )
    )


def node_modules():
    """Adresar s HyperspaceDB SDK. env NODE_PATH prebije; inak najde npx cache
    co obsahuje hyperspace-sdk-ts (bootstrap ho instaluje cez npx)."""
    if os.environ.get("NODE_PATH"):
        return os.environ["NODE_PATH"]
    for cand in glob.glob(os.path.join(HOME, ".npm", "_npx", "*", "node_modules")):
        if os.path.isdir(os.path.join(cand, "hyperspace-sdk-ts")) or glob.glob(
            os.path.join(cand, "*hyperspace*")
        ):
            return cand
    local = os.path.join(here, "node_modules")
    return local if os.path.isdir(local) else ""


def node_env():
    """os.environ s NODE_PATH nastavenym na detekovany node_modules."""
    nm = node_modules()
    return dict(os.environ, NODE_PATH=nm) if nm else dict(os.environ)


def venv_python():
    """Python z .venv-yar (torch+YAR embedder). env -> zolander_root/.venv-yar."""
    return os.environ.get("ZOL_VENV_PY") or os.path.join(
        zolander_root(), ".venv-yar", "bin", "python"
    )


# Pohodlne konstanty (vyhodnotene pri importe)
ZROOT = zolander_root()
ZOLO2 = zolo2_root()
HS = hs_mjs()
NODE = node_bin()
NODE_ENV = node_env()
STATE = os.path.join(ZROOT, "state")
LOGS = os.path.join(ZROOT, "logs")


if __name__ == "__main__":
    import json

    print(json.dumps({
        "HOME": HOME, "here": here, "ZROOT": ZROOT, "ZOLO2": ZOLO2,
        "HS": HS, "HS_exists": os.path.exists(HS),
        "NODE": NODE, "NODE_exists": os.path.exists(NODE) or bool(shutil.which("node")),
        "NODE_PATH": NODE_ENV.get("NODE_PATH", ""),
        "venv_python": venv_python(), "venv_exists": os.path.exists(venv_python()),
    }, indent=2, ensure_ascii=False))
