from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from ingestion.snapshots.store import (
    LocalStore,
    S3Store,
    SnapshotError,
    SnapshotStore,
)

BUCKET = "test-bucket"


@pytest.fixture
def s3_client() -> Iterator:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture(params=["local", "s3"])
def any_store(request, tmp_path: Path) -> SnapshotStore:
    if request.param == "local":
        return LocalStore(tmp_path / "store")
    client = request.getfixturevalue("s3_client")
    return S3Store(client, BUCKET, "raw/", tmp_path / "cache")


def _file(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


def test_put_and_read(any_store: SnapshotStore, tmp_path: Path):
    files = {"a.json": _file(tmp_path, "a.json", '{"a": 1}')}
    manifest = any_store.put_snapshot("kali", "1.0.0", files, {"version": "1.0.0"})

    assert any_store.exists("kali", "1.0.0")
    assert any_store.latest("kali") == "1.0.0"
    assert any_store.resolve("kali", "latest") == "1.0.0"
    assert any_store.manifest("kali", "1.0.0") == manifest
    assert any_store.fetch_file(manifest, "a.json").read_text() == '{"a": 1}'

    any_store.put_snapshot("kali", "1.1.0", files, {})
    assert any_store.latest("kali") == "1.1.0"
    assert any_store.resolve("kali", "1.0.0") == "1.0.0"


def test_snapshots_are_immutable(any_store: SnapshotStore, tmp_path: Path):
    files = {"a.json": _file(tmp_path, "a.json", "1")}
    any_store.put_snapshot("legi", "1", files, {})
    with pytest.raises(SnapshotError, match="already exists"):
        any_store.put_snapshot("legi", "1", files, {})


def test_missing(any_store: SnapshotStore, tmp_path: Path):
    with pytest.raises(SnapshotError, match="ingest fetch"):
        any_store.latest("legi")
    with pytest.raises(SnapshotError, match="not found"):
        any_store.manifest("legi", "1")
    manifest = any_store.put_snapshot(
        "legi", "1", {"a.json": _file(tmp_path, "a.json", "1")}, {}
    )
    with pytest.raises(SnapshotError, match="not in snapshot"):
        any_store.fetch_file(manifest, "b.json")


def test_local_store_detects_a_modified_file(tmp_path: Path):
    store = LocalStore(tmp_path / "store")
    manifest = store.put_snapshot(
        "legi", "1", {"a.json": _file(tmp_path, "a.json", "1")}, {}
    )
    (tmp_path / "store" / "legi" / "1" / "a.json").write_text("2")
    with pytest.raises(SnapshotError, match="does not match"):
        store.fetch_file(manifest, "a.json")


def test_s3_store_caches_and_checks_downloads(s3_client, tmp_path: Path):
    store = S3Store(s3_client, BUCKET, "raw/", tmp_path / "cache")
    manifest = store.put_snapshot(
        "legi", "1", {"a.json": _file(tmp_path, "a.json", "1")}, {}
    )
    keys = [o["Key"] for o in s3_client.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert sorted(keys) == [
        "raw/legi/1/a.json",
        "raw/legi/1/manifest.json",
        "raw/legi/LATEST.json",
    ]

    path = store.fetch_file(manifest, "a.json")
    s3_client.put_object(Bucket=BUCKET, Key="raw/legi/1/a.json", Body=b"2")
    # cached copy reused: the tampered object is not downloaded again
    assert store.fetch_file(manifest, "a.json") == path
    path.unlink()
    with pytest.raises(SnapshotError, match="does not match"):
        store.fetch_file(manifest, "a.json")
