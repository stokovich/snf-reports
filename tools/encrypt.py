"""Encrypts the report for the public site: gzip, then AES-256-GCM with a key from the site password.

python tools/encrypt.py <data.json> <out.enc>      env: SITE_PASSWORD

The page derives the same key in the browser (WebCrypto: PBKDF2-SHA256, ITERATIONS, SALT) and keeps the
derived key - never the password - when the viewer ticks "remember". The salt is fixed, so a remembered key
keeps working from one hourly build to the next; a new password gives a new key and the page asks again.
Needs the `cryptography` package (installed in the workflow).
"""
import base64
import gzip
import hashlib
import json
import os
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 600000
SALT = hashlib.sha256(b"snf-reports/v1").digest()[:16]


def key_from(password):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), SALT, ITERATIONS, dklen=32)


def encrypt(plain, password):
    iv = os.urandom(12)
    ct = AESGCM(key_from(password)).encrypt(iv, gzip.compress(plain, mtime=0), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": b64(SALT), "iv": b64(iv), "ct": b64(ct)}


def decrypt(env, password):
    raw = base64.b64decode
    return gzip.decompress(AESGCM(key_from(password)).decrypt(raw(env["iv"]), raw(env["ct"]), None))


def main():
    src, dst = sys.argv[1], sys.argv[2]
    password = os.environ.get("SITE_PASSWORD") or ""
    if len(password) < 8:
        sys.exit("SITE_PASSWORD is missing or shorter than 8 characters")
    plain = open(src, "rb").read()
    # "Update now" on the page: a token that can only start this repo's workflow, inside the encrypted report -
    # only those who know the password get it
    token = os.environ.get("DISPATCH_TOKEN")
    if token:
        data = json.loads(plain)
        data["dispatch"] = {"token": token, "repo": os.environ.get("GITHUB_REPOSITORY", ""),
                            "workflow": "build.yml", "ref": "main"}
        plain = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    env = encrypt(plain, password)
    if decrypt(env, password) != plain:
        sys.exit("round trip failed")
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", encoding="ascii") as f:
        json.dump(env, f)
    print(f"encrypted: {len(plain)} -> {os.path.getsize(dst)} bytes")


if __name__ == "__main__":
    main()
