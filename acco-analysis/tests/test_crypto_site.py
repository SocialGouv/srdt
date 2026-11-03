import shutil
import subprocess
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from acco_analysis import crypto_site

ITERATIONS = 1000  # the format is the same, the test is faster
DECRYPT = Path(__file__).parent / "node" / "decrypt.cjs"


def key(password: str = "correct horse", salt: bytes = b"0" * 16) -> bytes:
    return crypto_site.derive_key(password, salt, ITERATIONS)


def test_round_trip_and_a_fresh_iv_per_file():
    data = "Les horaires sont décalés en cas de canicule.".encode()
    first, second = crypto_site.encrypt(key(), data), crypto_site.encrypt(key(), data)
    assert first != second
    assert crypto_site.decrypt(key(), first) == data
    assert data not in first


def test_wrong_password_or_altered_file_is_refused():
    blob = crypto_site.encrypt(key(), b"secret")
    with pytest.raises(InvalidTag):
        crypto_site.decrypt(key("wrong"), blob)
    with pytest.raises(InvalidTag):
        crypto_site.decrypt(key(), blob[:-1] + bytes([blob[-1] ^ 1]))


def test_file_key_is_stable_per_salt_and_hides_the_id():
    a = crypto_site.file_key(b"s", "ACCOTEXT000001")
    assert a == crypto_site.file_key(b"s", "ACCOTEXT000001")
    assert a != crypto_site.file_key(b"t", "ACCOTEXT000001")
    assert len(a) == 16 and "ACCOTEXT" not in a


def test_weak_password():
    assert crypto_site.weak_password("short")
    assert not crypto_site.weak_password("a long enough passphrase indeed")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_browser_code_reads_what_python_wrote(tmp_path: Path):
    salt = crypto_site.new_salt()
    text = "Canicule : télétravail « à 33 °C » ✓ " * 50
    file = tmp_path / "x.dat"
    file.write_bytes(
        crypto_site.encrypt(
            crypto_site.derive_key("pw", salt, ITERATIONS), text.encode()
        )
    )

    def run(password: str):
        return subprocess.run(
            ["node", str(DECRYPT), str(file), password, salt.hex(), str(ITERATIONS)],
            capture_output=True,
            text=True,
        )

    ok = run("pw")
    assert ok.returncode == 0 and ok.stdout == text
    assert run("nope").returncode != 0
