"""Hosting of the labelling page: a public static page, the data in a private repo.

`label-publish` splits what `label-export` puts in one file:

- `page/index.html`, for a public GitHub Pages repo: the app without any question
  or answer, and a vault holding a fine-grained GitHub token, encrypted with the
  password given to the labellers;
- `data/data.json`, for the private data repo: the page data (questions, blinded
  answers, sources, criteria), exactly as the self-contained page embeds it.

In the browser the password decrypts the token (WebCrypto), the page reads
`data.json` through the GitHub contents API and commits the labels to
`labels.json` in the same repo (one labeller), where `label-import` reads them
back (`fetch_labels`). The key that unblinds the answers stays in the
run's labelling directory, in neither repo.

Vault: AES-256-GCM, key = PBKDF2-HMAC-SHA256(NFC password, random 16-byte salt,
600 000 iterations), random 12-byte IV; the ciphertext ends with the GCM tag, as
WebCrypto expects. Anyone with the password gets a token that can write the data
repo: scope the token to that repo only and give it an expiry date.
"""

import base64
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from answer_eval.labelling import render_page

ITERATIONS = 600_000
PASSWORD_ENV = "LABEL_PASSWORD"
TOKEN_ENV = "LABEL_GITHUB_TOKEN"
PAGE_FILE = Path("page") / "index.html"
TARGET_FILE = "publish.json"  # in the run's labelling dir: where the labels live
LABELS_FILE = "labels.json"
GITHUB_API = "https://api.github.com"
DATA_DIR = Path("data")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DATA_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*\.json$")


class PublishError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations
    )
    # NFC: the same password typed with composed or decomposed accents.
    return kdf.derive(unicodedata.normalize("NFC", password).encode("utf-8"))


def encrypt_secret(
    secret: str, password: str, *, iterations: int = ITERATIONS
) -> dict[str, Any]:
    """The vault fields for `secret` (base64): what the page's `decryptVault`
    reads."""
    salt, iv = os.urandom(16), os.urandom(12)
    ciphertext = AESGCM(_key(password, salt, iterations)).encrypt(
        iv, secret.encode("utf-8"), None
    )
    return {
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": iterations,
        "salt": _b64(salt),
        "cipher": "AES-256-GCM",
        "iv": _b64(iv),
        "ciphertext": _b64(ciphertext),
    }


def decrypt_secret(vault: dict[str, Any], password: str) -> str:
    """The inverse of `encrypt_secret` (raises `cryptography`'s InvalidTag on a
    wrong password)."""
    key = _key(password, base64.b64decode(vault["salt"]), vault["iterations"])
    plain = AESGCM(key).decrypt(
        base64.b64decode(vault["iv"]), base64.b64decode(vault["ciphertext"]), None
    )
    return plain.decode("utf-8")


def secrets_from_env() -> tuple[str, str]:
    """(password, token) from LABEL_PASSWORD and LABEL_GITHUB_TOKEN."""
    missing = [name for name in (PASSWORD_ENV, TOKEN_ENV) if not os.environ.get(name)]
    if missing:
        raise PublishError(
            f"set {' and '.join(missing)} (the labellers' password and a "
            "fine-grained GitHub token with Contents read/write on the data repo)"
        )
    return os.environ[PASSWORD_ENV], os.environ[TOKEN_ENV]


def token_from_env() -> str:
    if not os.environ.get(TOKEN_ENV):
        raise PublishError(
            f"set {TOKEN_ENV} (a GitHub token that can read the data repo)"
        )
    return os.environ[TOKEN_ENV]


def check_target(repo: str, data_path: str) -> None:
    if not _REPO.match(repo):
        raise PublishError(f"--repo {repo!r} is not OWNER/NAME")
    if not _DATA_PATH.match(data_path) or ".." in data_path.split("/"):
        raise PublishError(
            f"--data-path {data_path!r} must be a relative path to a .json file"
        )


def publish(
    data: dict[str, Any],
    out_dir: Path,
    *,
    repo: str,
    data_path: str,
    password: str,
    token: str,
    iterations: int = ITERATIONS,
) -> tuple[Path, Path]:
    """Write the public page and the private data under `out_dir`; returns their
    paths."""
    check_target(repo, data_path)
    vault = {
        "version": 1,
        "title": data["title"],
        "repo": repo,
        "data_path": data_path,
        "labels_path": LABELS_FILE,
        **encrypt_secret(token, password, iterations=iterations),
    }
    page = out_dir / PAGE_FILE
    data_file = out_dir / DATA_DIR / data_path
    page.parent.mkdir(parents=True, exist_ok=True)
    data_file.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(render_page(vault=vault), encoding="utf-8")
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return page, data_file


def fetch_labels(
    repo: str, token: str, dest: Path, client: httpx.Client | None = None
) -> Path | None:
    """Copy the labels file of the data repo to `dest`; None when nothing has been
    saved yet."""
    check_target(repo, "data.json")
    url = f"{GITHUB_API}/repos/{repo}/contents/{LABELS_FILE}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
    }
    with client or httpx.Client(timeout=60) as http:
        response = http.get(url, headers=headers)
    if response.status_code == 404:
        return None
    if response.status_code in (401, 403):
        raise PublishError(
            f"GitHub refused the token for {repo} (HTTP {response.status_code})"
        )
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return dest
