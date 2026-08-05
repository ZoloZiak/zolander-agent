#!/usr/bin/env python3
"""Zolander F1 — vygeneruje trvalu Ed25519 identitu.
Idempotentne: ak kluc uz existuje, NEPREPISE ho (chrani identitu).
Zapise:
  identity/zolander_ed25519.key   (PEM private, chmod 600)
  identity/zolander_ed25519.pub   (PEM public)
  identity/fingerprint.txt        (SHA-256 hex verejneho kluca = A2A identita)
"""
import os
import hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

BASE = os.path.expanduser("~/zolander/identity")
KEY = os.path.join(BASE, "zolander_ed25519.key")
PUB = os.path.join(BASE, "zolander_ed25519.pub")
FP = os.path.join(BASE, "fingerprint.txt")

os.makedirs(BASE, exist_ok=True)

if os.path.exists(KEY):
    print("EXISTUJE: kluc uz je, neprepisujem.", KEY)
    _pw = os.environ.get("ZOLANDER_KEY_PASSPHRASE")
    _pwb = _pw.encode("utf-8") if _pw else None
    priv = serialization.load_pem_private_key(open(KEY, "rb").read(), password=_pwb)
else:
    priv = Ed25519PrivateKey.generate()
    # Kluc at-rest: ak je heslo v env ZOLANDER_KEY_PASSPHRASE, sifruj (PKCS8 +
    # BestAvailableEncryption). Inak necheme robit bezpecnostne DIVADLO — heslo
    # ulozene vedla kluca na disku by DLP/endpoint aj tak precital, nulovy zisk.
    # Preto: bez env hesla -> kluc ostane nesifrovany, ALE nahlas varujeme.
    _pw = os.environ.get("ZOLANDER_KEY_PASSPHRASE")
    if _pw:
        enc = serialization.BestAvailableEncryption(_pw.encode("utf-8"))
    else:
        enc = serialization.NoEncryption()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=enc,
    )
    with open(KEY, "wb") as f:
        f.write(pem)
    os.chmod(KEY, 0o600)
    if _pw:
        print("VYTVORENE (sifrovane heslom z ZOLANDER_KEY_PASSPHRASE):", KEY)
    else:
        print("VYTVORENE:", KEY)
        print("!! VAROVANIE: privatny kluc je NESIFROVANY na disku (chmod 600).")
        print("!! Pre sifrovanie at-rest nastav env ZOLANDER_KEY_PASSPHRASE a")
        print("!! vygeneruj kluc nanovo. Heslo drz MIMO disku (nie vedla kluca).")

pub = priv.public_key()
pub_pem = pub.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
with open(PUB, "wb") as f:
    f.write(pub_pem)

raw = pub.public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
fp = hashlib.sha256(raw).hexdigest()
with open(FP, "w") as f:
    f.write(fp + "\n")

print("PUBKEY (raw hex):", raw.hex())
print("FINGERPRINT (sha256):", fp)
