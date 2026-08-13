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
    priv = serialization.load_pem_private_key(open(KEY, "rb").read(), password=None)
else:
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(KEY, "wb") as f:
        f.write(pem)
    os.chmod(KEY, 0o600)
    print("VYTVORENE:", KEY)

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
