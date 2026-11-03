"""Encryption of the published site: PBKDF2 -> AES-256-GCM over gzipped data.

The format is read by `pages/gate.js` in the browser (WebCrypto), so the two must stay
in step: a file is `iv (12 bytes) + AES-GCM(key, gzip(data))`, the key is
PBKDF2-HMAC-SHA256(password, salt, iterations) with the salt and iterations published
in `manifest.json`. One key is derived per build and every file gets its own random IV.
"""

import gzip
import hashlib
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITERATIONS = 600_000
SALT_BYTES = 16
IV_BYTES = 12
MIN_PASSWORD = 20  # characters; a passphrase of 6 or more words is far above it


def new_salt() -> bytes:
    return os.urandom(SALT_BYTES)


def derive_key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt(key: bytes, data: bytes) -> bytes:
    iv = os.urandom(IV_BYTES)
    # mtime=0: the same data compresses to the same bytes
    return iv + AESGCM(key).encrypt(iv, gzip.compress(data, mtime=0), None)


def decrypt(key: bytes, blob: bytes) -> bytes:
    """Raises `cryptography.exceptions.InvalidTag` on a wrong key or altered file."""
    return gzip.decompress(AESGCM(key).decrypt(blob[:IV_BYTES], blob[IV_BYTES:], None))


def file_key(salt: bytes, agreement_id: str) -> str:
    """Public file name of an agreement: it does not reveal which ones are published."""
    return hashlib.sha256(salt + agreement_id.encode("utf-8")).hexdigest()[:16]


def weak_password(password: str) -> bool:
    return len(password) < MIN_PASSWORD
