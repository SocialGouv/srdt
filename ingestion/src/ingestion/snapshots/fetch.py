"""Download the latest upstream data and store it as a snapshot.

- legi, kali: the @socialgouv/{legi,kali}-data npm packages (published daily);
  the snapshot id is the package version. Or a local data/ directory of those
  repositories (`--from-dir`): the published kali-data has most agreements empty
  since 2023, so KALI comes from a checkout regenerated with its fetch script.
- judilibre: the decisions since 1990 from the PISTE API, one file per year; the
  snapshot id is the UTC date. A refresh only downloads the last years and carries
  the earlier ones over from the latest snapshot. Or a local directory of year
  files (`--from-dir`).
"""

import base64
import hashlib
import json
import logging
import re
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ingestion.snapshots.store import (
    Manifest,
    SnapshotError,
    SnapshotStore,
    file_sha256,
)
from ingestion.sources import judilibre
from ingestion.sources.kali import is_agreement_file
from ingestion.sources.legi import CODE_DU_TRAVAIL_FILE

NPM_REGISTRY = "https://registry.npmjs.org"
JUDILIBRE_START_YEAR = 1990
# a re-downloaded year with fewer decisions than this share of the latest snapshot's
# is refused (an API hiccup must not wipe a year)
SHRINK_THRESHOLD = 0.9

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NpmDataset:
    package: str
    # keep a file of the package data/ directory (name without directory)
    keep: Callable[[str], bool]


NPM_DATASETS: dict[str, NpmDataset] = {
    "legi": NpmDataset("@socialgouv/legi-data", lambda n: n == CODE_DU_TRAVAIL_FILE),
    "kali": NpmDataset("@socialgouv/kali-data", is_agreement_file),
}

DATA_MEMBER = re.compile(r"^package/data/([^/]+)$")
YEAR_FILE = re.compile(r"^(\d{4})\.json$")


def _check_integrity(path: Path, integrity: str) -> None:
    # npm "dist.integrity" is an SRI string: sha512-<base64 digest>
    algorithm, _, expected = integrity.partition("-")
    if algorithm != "sha512":
        raise SnapshotError(f"Unsupported integrity algorithm: {algorithm}")
    digest = hashlib.sha512()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    if base64.b64encode(digest.digest()).decode() != expected:
        raise SnapshotError(f"{path.name} does not match its npm integrity")


def fetch_npm(
    store: SnapshotStore, dataset: str, http: httpx.Client | None = None
) -> Manifest | None:
    """Snapshot the latest version of the npm package; None if already stored."""
    spec = NPM_DATASETS[dataset]
    http = http or httpx.Client(timeout=60, follow_redirects=True)

    response = http.get(f"{NPM_REGISTRY}/{spec.package}/latest")
    response.raise_for_status()
    latest = response.json()
    version = latest["version"]
    dist = latest["dist"]

    if store.exists(dataset, version):
        logger.info(f"{dataset}: {spec.package}@{version} already stored")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tarball = Path(tmp) / "package.tgz"
        logger.info(f"{dataset}: download {spec.package}@{version}")
        with http.stream("GET", dist["tarball"]) as stream:
            stream.raise_for_status()
            with open(tarball, "wb") as f:
                for chunk in stream.iter_bytes():
                    f.write(chunk)
        _check_integrity(tarball, dist["integrity"])

        files: dict[str, Path] = {}
        out_dir = Path(tmp) / "files"
        out_dir.mkdir()
        with tarfile.open(tarball, "r:gz") as tar:
            for member in tar:
                match = DATA_MEMBER.match(member.name)
                if not (member.isfile() and match and spec.keep(match.group(1))):
                    continue
                # written under our own name: member paths are never trusted
                target = out_dir / match.group(1)
                source = tar.extractfile(member)
                if source is None:
                    continue
                with source, open(target, "wb") as f:
                    shutil.copyfileobj(source, f)
                files[match.group(1)] = target

        if not files:
            raise SnapshotError(f"No data file kept from {spec.package}@{version}")
        upstream = {
            "package": spec.package,
            "version": version,
            "tarball": dist["tarball"],
            "integrity": dist["integrity"],
        }
        return _put(store, dataset, version, files, upstream)


def _keep_for(dataset: str) -> Callable[[str], bool]:
    if dataset == "judilibre":
        return lambda name: YEAR_FILE.match(name) is not None
    return NPM_DATASETS[dataset].keep


def import_dir(
    store: SnapshotStore,
    dataset: str,
    directory: Path,
    now: datetime | None = None,
) -> Manifest | None:
    """Snapshot a local directory: the data/ directory of a legi-data or kali-data
    checkout, or the year files of Judilibre. None if the same content is already
    stored."""
    keep = _keep_for(dataset)
    files = {
        p.name: p for p in sorted(directory.iterdir()) if p.is_file() and keep(p.name)
    }
    if not files:
        raise SnapshotError(f"No {dataset} data file in {directory}")

    with tempfile.TemporaryDirectory() as tmp:
        if dataset == "judilibre":
            files = _normalised_copies(files, Path(tmp))

        content = hashlib.sha256()
        for name, path in files.items():
            content.update(f"{name}\0{file_sha256(path)}\n".encode())
        upstream: dict = {
            "source_dir": str(directory.resolve()),
            "content_sha256": content.hexdigest(),
        }
        if dataset == "judilibre":
            label = (now or datetime.now(UTC)).strftime("%Y%m%d")
        else:
            label = _package_version(directory)
            upstream |= {"package": NPM_DATASETS[dataset].package, "version": label}
        # same content, same id: importing an unchanged directory again is a no-op
        snapshot_id = f"{label}-local.{content.hexdigest()[:8]}"
        if store.exists(dataset, snapshot_id):
            logger.info(f"{dataset}: snapshot {snapshot_id} already stored")
            return None
        return _put(store, dataset, snapshot_id, files, upstream)


def _normalised_copies(files: dict[str, Path], directory: Path) -> dict[str, Path]:
    copies = {}
    for name, path in files.items():
        decisions = _normalise_decisions(json.loads(path.read_text()))
        copies[name] = directory / name
        copies[name].write_text(json.dumps(decisions))
    return copies


def _package_version(directory: Path) -> str:
    # data/ sits next to the package.json of the repository
    package = directory.resolve().parent / "package.json"
    if package.exists():
        return str(json.loads(package.read_text()).get("version", "0"))
    return "0"


def _put(
    store: SnapshotStore,
    dataset: str,
    snapshot_id: str,
    files: dict[str, Path],
    upstream: dict,
) -> Manifest:
    if dataset == "kali":
        empty = [name for name, path in files.items() if _is_empty_agreement(path)]
        upstream["empty_agreements"] = len(empty)
        if empty:
            logger.warning(
                f"kali: {len(empty)}/{len(files)} agreements without content"
            )
    logger.info(f"{dataset}: store {len(files)} files as {snapshot_id}")
    return store.put_snapshot(dataset, snapshot_id, files, upstream)


def _is_empty_agreement(path: Path) -> bool:
    with open(path) as f:
        return not json.load(f).get("children")


def _year_of(path: str) -> int | None:
    match = YEAR_FILE.match(path)
    return int(match.group(1)) if match else None


def _normalise_decisions(decisions: list[dict]) -> list[dict]:
    """One entry per decision, in a fixed order: the API order is not stable, and
    unchanged data must give identical files."""
    by_id: dict[str | None, dict] = {}
    for decision in decisions:
        by_id.setdefault(decision.get("id"), decision)
    return sorted(
        by_id.values(),
        key=lambda d: (d.get("decision_date") or "", d.get("id") or ""),
    )


def _latest_snapshot(store: SnapshotStore, dataset: str) -> Manifest | None:
    try:
        return store.manifest(dataset, store.latest(dataset))
    except SnapshotError:
        return None


def fetch_judilibre(
    store: SnapshotStore,
    client: judilibre.JudilibreClient,
    start_year: int = JUDILIBRE_START_YEAR,
    now: datetime | None = None,
    since_year: int | None = None,
    full: bool = False,
    allow_shrink: bool = False,
) -> Manifest | None:
    """Snapshot the decisions since `start_year`, one file per year.

    Bulletin publications and summary edits land on past years, so a refresh
    downloads again from `since_year` (default: last year) and carries the earlier
    years over from the latest snapshot. Without a previous snapshot, or with
    `full`, every year is downloaded.

    Returns None when today's snapshot is already stored or nothing changed.
    """
    now = now or datetime.now(UTC)
    snapshot_id = now.strftime("%Y%m%d")
    if store.exists("judilibre", snapshot_id):
        logger.info(f"judilibre: snapshot {snapshot_id} already stored")
        return None

    previous = _latest_snapshot(store, "judilibre")
    previous_years = sorted(
        y for p in (previous.paths() if previous else []) if (y := _year_of(p))
    )

    first_year = start_year
    carried: list[str] = []
    if previous and previous_years and not full:
        wanted = since_year if since_year is not None else now.year - 1
        # no gap between the carried years and the downloaded ones
        first_year = max(start_year, min(wanted, previous_years[-1]))
        carried = [
            p
            for p in previous.paths()
            if (y := _year_of(p)) is not None and y < first_year
        ]
    mode = "window" if carried else "full"
    logger.info(f"judilibre: {mode} refresh, years {first_year}-{now.year}")

    with tempfile.TemporaryDirectory() as tmp:
        files: dict[str, Path] = {}
        if previous:
            files = {p: store.fetch_file(previous, p) for p in carried}

        shrunk = []
        for year in range(first_year, now.year + 1):
            decisions = _normalise_decisions(
                client.get_decisions_between_dates(f"{year}-01-01", f"{year}-12-31")
            )
            name = f"{year}.json"
            before = _decision_count(store, previous, name)
            logger.info(
                f"judilibre: {len(decisions)} decisions in {year}"
                + (f" (latest snapshot: {before})" if before is not None else "")
            )
            if before and len(decisions) < SHRINK_THRESHOLD * before:
                shrunk.append(f"{year}: {before} -> {len(decisions)}")
            path = Path(tmp) / name
            path.write_text(json.dumps(decisions))
            files[name] = path

        if shrunk and not allow_shrink:
            raise SnapshotError(
                "judilibre: fewer decisions than in the latest snapshot "
                f"({', '.join(shrunk)}); pass --allow-shrink if expected"
            )
        if previous and {n: file_sha256(p) for n, p in files.items()} == {
            f.path: f.sha256 for f in previous.files
        }:
            logger.info(f"judilibre: unchanged since {previous.snapshot_id}")
            return None

        years = [y for n in files if (y := _year_of(n)) is not None]
        return store.put_snapshot(
            "judilibre",
            snapshot_id,
            files,
            upstream={
                "api": client.base_url,
                "filters": {
                    "jurisdiction": judilibre.JURISDICTION,
                    "chamber": judilibre.CHAMBER,
                    "publication": judilibre.PUBLICATION,
                },
                "mode": mode,
                "years": [min(years), now.year],
                "fetched_years": [first_year, now.year],
                "carried_from": previous.snapshot_id if previous and carried else None,
            },
        )


def _decision_count(
    store: SnapshotStore, manifest: Manifest | None, name: str
) -> int | None:
    if manifest is None or name not in manifest.paths():
        return None
    return len(json.loads(store.fetch_file(manifest, name).read_text()))
