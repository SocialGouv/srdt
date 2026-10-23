"""Immutable snapshots of the raw source files, on S3 or in a local directory.

{prefix}{dataset}/{snapshot_id}/manifest.json
{prefix}{dataset}/{snapshot_id}/<files>
{prefix}{dataset}/LATEST.json      -> {"snapshot_id": ...}, written last
"""

import hashlib
import json
import shutil
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
from pydantic import BaseModel

from ingestion.settings import Settings, secret

MANIFEST = "manifest.json"
LATEST = "LATEST.json"


class SnapshotError(RuntimeError):
    pass


class ManifestFile(BaseModel):
    path: str
    sha256: str
    size: int


class Manifest(BaseModel):
    dataset: str
    snapshot_id: str
    fetched_at: datetime
    # where the files come from (package name and version, API filters...)
    upstream: dict[str, Any]
    files: list[ManifestFile]

    def paths(self) -> list[str]:
        return [f.path for f in self.files]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class SnapshotStore(ABC):
    @abstractmethod
    def _read(self, key: str) -> bytes | None: ...

    @abstractmethod
    def _write(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def _upload(self, key: str, source: Path) -> None: ...

    @abstractmethod
    def _local_copy(self, key: str, file: ManifestFile) -> Path:
        """Local path holding the file of `key`, checked against the manifest."""

    def _key(self, dataset: str, *parts: str) -> str:
        return "/".join([dataset, *parts])

    def exists(self, dataset: str, snapshot_id: str) -> bool:
        return self._read(self._key(dataset, snapshot_id, MANIFEST)) is not None

    def latest(self, dataset: str) -> str:
        data = self._read(self._key(dataset, LATEST))
        if data is None:
            raise SnapshotError(f"No snapshot of {dataset} yet (run ingest fetch)")
        return json.loads(data)["snapshot_id"]

    def resolve(self, dataset: str, ref: str) -> str:
        return self.latest(dataset) if ref == "latest" else ref

    def manifest(self, dataset: str, snapshot_id: str) -> Manifest:
        data = self._read(self._key(dataset, snapshot_id, MANIFEST))
        if data is None:
            raise SnapshotError(f"Snapshot {dataset}/{snapshot_id} not found")
        return Manifest.model_validate_json(data)

    def fetch_file(self, manifest: Manifest, path: str) -> Path:
        file = next((f for f in manifest.files if f.path == path), None)
        if file is None:
            raise SnapshotError(
                f"{path} is not in snapshot {manifest.dataset}/{manifest.snapshot_id}"
            )
        key = self._key(manifest.dataset, manifest.snapshot_id, path)
        return self._local_copy(key, file)

    def put_snapshot(
        self,
        dataset: str,
        snapshot_id: str,
        files: dict[str, Path],
        upstream: dict[str, Any],
    ) -> Manifest:
        """Upload `files` (snapshot path -> local file), then the manifest, then
        point LATEST to the snapshot."""
        if self.exists(dataset, snapshot_id):
            raise SnapshotError(f"Snapshot {dataset}/{snapshot_id} already exists")
        entries = []
        for path, source in sorted(files.items()):
            entries.append(
                ManifestFile(
                    path=path, sha256=file_sha256(source), size=source.stat().st_size
                )
            )
            self._upload(self._key(dataset, snapshot_id, path), source)
        manifest = Manifest(
            dataset=dataset,
            snapshot_id=snapshot_id,
            fetched_at=datetime.now(UTC),
            upstream=upstream,
            files=entries,
        )
        self._write(
            self._key(dataset, snapshot_id, MANIFEST),
            manifest.model_dump_json(indent=2).encode(),
        )
        self._write(
            self._key(dataset, LATEST),
            json.dumps({"snapshot_id": snapshot_id}).encode(),
        )
        return manifest


class LocalStore(SnapshotStore):
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key

    def _read(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    def _write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _upload(self, key: str, source: Path) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)

    def _local_copy(self, key: str, file: ManifestFile) -> Path:
        path = self._path(key)
        if not path.exists() or file_sha256(path) != file.sha256:
            raise SnapshotError(f"{key} is missing or does not match its manifest")
        return path


class S3Store(SnapshotStore):
    def __init__(self, client: Any, bucket: str, prefix: str, cache_dir: Path):
        self.client = client
        self.bucket = bucket
        self.prefix = prefix
        self.cache_dir = cache_dir

    def _read(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)
        except ClientError as e:
            # S3-compatible stores do not all return the NoSuchKey code
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise
        return response["Body"].read()

    def _write(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data)

    def _upload(self, key: str, source: Path) -> None:
        self.client.upload_file(str(source), self.bucket, self.prefix + key)

    def _local_copy(self, key: str, file: ManifestFile) -> Path:
        # snapshots are immutable: a cached copy with the right hash is reused
        path = self.cache_dir / key
        if path.exists() and file_sha256(path) == file.sha256:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        self.client.download_file(self.bucket, self.prefix + key, str(tmp))
        if file_sha256(tmp) != file.sha256:
            tmp.unlink()
            raise SnapshotError(f"{key} does not match its manifest")
        tmp.replace(path)
        return path


def make_store(settings: Settings, kind: str | None = None) -> SnapshotStore:
    kind = kind or settings.snapshot_store
    if kind == "local":
        return LocalStore(settings.snapshot_local_dir)

    import boto3

    settings.require("s3_bucket")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=secret(settings.aws_secret_access_key) or None,
    )
    return S3Store(
        client,
        bucket=str(settings.s3_bucket),
        prefix=settings.s3_prefix,
        cache_dir=settings.snapshot_cache_dir,
    )
