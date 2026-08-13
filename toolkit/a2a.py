#!/usr/bin/env python3
"""a2a.py — Zolander F12: podpisany peer-to-peer most (guestbook / inbox).

Nie je to "vedomie" ani "socialna siet". Je to MINIMALNA zaruka dvoch veci pri
sprave od ineho agenta (peer):
  1) IDENTITA  — kto to naozaj napisal (Ed25519 podpis proti jeho pubkey),
  2) INTEGRITA — ze sprava nebola po ceste zmenena (podpis kryje presny obsah).

Obsah/argumentacia s peerom je az VRSTVA NAD tymto. Most sam NEVOLA ziadny LLM
a je plne overitelny offline.

Stavia na F1 identite (gen_identity.py):
  identity/zolander_ed25519.key   PEM PKCS8 privatny (chmod 600) — NIKDY do repa
  identity/fingerprint.txt        SHA-256 hex raw pubkey = nase A2A ID

Peer pubkeye zijú v known_peers/<fp>.pub (raw hex, 64 znakov). Doverujeme len fp,
ktore sme explicitne pridali cez `trust`.

KANONICKY PODPIS: podpisuje sa presne UTF-8 bajty kanonickeho JSONu spravy bez
pola "sig": json.dumps({from_fp, ts, body}, sort_keys=True, separators=(",",":"),
ensure_ascii=False). Verify prepocita ten isty tvar. Akakolvek zmena
body/ts/from_fp => iny kanonicky tvar => podpis NESEDI => FAIL.

Pouzitie (POZOR: systemovy python3 — ma cryptography; .venv-yar je torch-only!):
  P=/usr/bin/python3
  echo "ahoj peer" | $P a2a.py post                 # podpis + zapis do inbox
  $P a2a.py read                                     # vypis inbox, overuj kazdu
  echo '{...sprava...}' | $P a2a.py verify           # over jednu spravu zo stdin
  $P a2a.py trust <fp> <pub_raw_hex_file>            # pridaj peer pubkey
  $P a2a.py whoami                                   # nas fingerprint + pubkey
"""
import os
import sys
import json
import time
import hashlib
import binascii

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
IDENTITY = os.path.join(ROOT, "identity")
KEY = os.path.join(IDENTITY, "zolander_ed25519.key")
FP = os.path.join(IDENTITY, "fingerprint.txt")
PEERS = os.path.join(ROOT, "known_peers")
INBOX = os.path.join(ROOT, "inbox", "inbox.jsonl")


def _load_priv():
    if not os.path.exists(KEY):
        raise SystemExit("CHYBA: chyba privatny kluc. Spusti gen_identity.py najprv.")
    return serialization.load_pem_private_key(open(KEY, "rb").read(), password=None)


def _raw_pub_hex(pub):
    return pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def _fp_from_raw_hex(raw_hex):
    return hashlib.sha256(binascii.unhexlify(raw_hex)).hexdigest()


def _my_fp():
    if os.path.exists(FP):
        return open(FP).read().strip()
    return _fp_from_raw_hex(_raw_pub_hex(_load_priv().public_key()))


def _canonical(msg):
    """Presne bajty, ktore sa podpisuju: sprava BEZ pola 'sig', kanonicky JSON."""
    core = {"from_fp": msg["from_fp"], "ts": msg["ts"], "body": msg["body"]}
    return json.dumps(core, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _pub_for_fp(fp):
    """Vrat Ed25519PublicKey pre dany fp: nas vlastny alebo z known_peers/."""
    my = _my_fp()
    if fp == my:
        return _load_priv().public_key()
    path = os.path.join(PEERS, fp + ".pub")
    if not os.path.exists(path):
        return None
    raw_hex = open(path).read().strip()
    # obrana: subor musi sediet na svoj vlastny fp (inak niekto podstrcil ciziu pubkey)
    if _fp_from_raw_hex(raw_hex) != fp:
        raise ValueError(f"known_peers/{fp}.pub NESEDI na svoj fingerprint — odmietam")
    return Ed25519PublicKey.from_public_bytes(binascii.unhexlify(raw_hex))


def sign_body(body):
    priv = _load_priv()
    msg = {
        "from_fp": _my_fp(),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "body": body,
    }
    sig = priv.sign(_canonical(msg))
    msg["sig"] = sig.hex()
    return msg


def verify_msg(msg):
    """Vrat (ok: bool, dovod: str)."""
    for f in ("from_fp", "ts", "body", "sig"):
        if f not in msg:
            return False, f"chyba pole '{f}'"
    pub = _pub_for_fp(msg["from_fp"])
    if pub is None:
        return False, f"neznamy odosielatel (fp={msg['from_fp'][:12]}...) — nie je v known_peers, netrust-nuty"
    try:
        pub.verify(binascii.unhexlify(msg["sig"]), _canonical(msg))
        return True, "podpis OK, identita a integrita potvrdena"
    except InvalidSignature:
        return False, "PODPIS NESEDI — sprava zmenena alebo cudzi kluc"
    except Exception as e:
        return False, f"chyba overenia: {e}"


def cmd_post():
    body = sys.stdin.read().strip()
    if not body:
        raise SystemExit("prazdne telo — nic neposielam")
    msg = sign_body(body)
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    with open(INBOX, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    print(json.dumps({"posted": True, "from_fp": msg["from_fp"][:12] + "...",
                      "ts": msg["ts"], "sig": msg["sig"][:16] + "..."},
                     ensure_ascii=False))


def cmd_read():
    if not os.path.exists(INBOX):
        print(json.dumps({"inbox": [], "note": "prazdny inbox"}, ensure_ascii=False))
        return
    out = []
    for line in open(INBOX, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out.append({"ok": False, "dovod": "nevalidny JSON riadok"})
            continue
        ok, why = verify_msg(msg)
        out.append({"ok": ok, "from": msg.get("from_fp", "?")[:12] + "...",
                    "ts": msg.get("ts"), "body": msg.get("body", "")[:120],
                    "dovod": why})
    n_ok = sum(1 for m in out if m["ok"])
    print(json.dumps({"inbox": out, "spolu": len(out), "overenych": n_ok,
                      "neoverenych": len(out) - n_ok}, ensure_ascii=False, indent=2))


def cmd_verify():
    raw = sys.stdin.read().strip()
    msg = json.loads(raw)
    ok, why = verify_msg(msg)
    print(json.dumps({"ok": ok, "dovod": why}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


def cmd_trust():
    if len(sys.argv) < 4:
        raise SystemExit("pouzitie: a2a.py trust <fp> <subor_s_raw_hex_pubkey>")
    fp, pubfile = sys.argv[2], sys.argv[3]
    raw_hex = open(pubfile).read().strip()
    if _fp_from_raw_hex(raw_hex) != fp:
        raise SystemExit(f"ODMIETAM: pubkey nesedi na fp {fp} (fp je sha256 pubkey)")
    os.makedirs(PEERS, exist_ok=True)
    with open(os.path.join(PEERS, fp + ".pub"), "w") as f:
        f.write(raw_hex + "\n")
    print(json.dumps({"trusted": fp, "note": "peer pridany do known_peers"},
                     ensure_ascii=False))


def cmd_whoami():
    priv = _load_priv()
    raw_hex = _raw_pub_hex(priv.public_key())
    print(json.dumps({"fingerprint": _my_fp(), "pubkey_raw_hex": raw_hex},
                     ensure_ascii=False, indent=2))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "read"
    {
        "post": cmd_post,
        "read": cmd_read,
        "verify": cmd_verify,
        "trust": cmd_trust,
        "whoami": cmd_whoami,
    }.get(cmd, lambda: (_ for _ in ()).throw(
        SystemExit(f"neznamy prikaz: {cmd} (post|read|verify|trust|whoami)")))()


if __name__ == "__main__":
    main()
