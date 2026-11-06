import base64
import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest

from ingestion.snapshots.fetch import fetch_judilibre, fetch_npm, import_dir
from ingestion.snapshots.store import LocalStore, SnapshotError
from ingestion.sources.judilibre import JudilibreClient

TARBALL_URL = "https://registry.npmjs.org/pkg/-/pkg-2.0.0.tgz"


def _tarball(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _registry(tarball: bytes, integrity: str | None = None) -> httpx.Client:
    if integrity is None:
        digest = base64.b64encode(hashlib.sha512(tarball).digest()).decode()
        integrity = f"sha512-{digest}"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/latest"):
            return httpx.Response(
                200,
                json={
                    "version": "2.0.0",
                    "dist": {"tarball": TARBALL_URL, "integrity": integrity},
                },
            )
        if str(request.url) == TARBALL_URL:
            return httpx.Response(200, content=tarball)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


KALI_TARBALL = _tarball(
    {
        "package/package.json": b"{}",
        "package/data/index.json": b"[]",
        "package/data/KALICONT000000000001.json": b'{"a": 1}',
        "package/data/KALICONT000000000002.json": b'{"a": 2}',
        "package/data/articles/KALICONT000000000003.json": b"{}",
        "package/data/../../KALICONT000000000004.json": b"{}",
    }
)


def test_fetch_npm_keeps_only_the_agreements(tmp_path: Path):
    store = LocalStore(tmp_path)
    manifest = fetch_npm(store, "kali", _registry(KALI_TARBALL))

    assert manifest is not None
    assert manifest.snapshot_id == "2.0.0"
    assert manifest.paths() == [
        "KALICONT000000000001.json",
        "KALICONT000000000002.json",
    ]
    assert manifest.upstream["package"] == "@socialgouv/kali-data"
    assert store.latest("kali") == "2.0.0"
    path = store.fetch_file(manifest, "KALICONT000000000002.json")
    assert json.loads(path.read_text()) == {"a": 2}


def test_fetch_npm_is_a_no_op_when_the_version_is_stored(tmp_path: Path):
    store = LocalStore(tmp_path)
    assert fetch_npm(store, "kali", _registry(KALI_TARBALL)) is not None
    assert fetch_npm(store, "kali", _registry(KALI_TARBALL)) is None


def test_fetch_npm_checks_the_integrity(tmp_path: Path):
    store = LocalStore(tmp_path)
    wrong = "sha512-" + base64.b64encode(b"0" * 64).decode()
    with pytest.raises(SnapshotError, match="integrity"):
        fetch_npm(store, "kali", _registry(KALI_TARBALL, wrong))
    assert not store.exists("kali", "2.0.0")


def test_fetch_npm_legi_keeps_the_code_du_travail(tmp_path: Path):
    tarball = _tarball(
        {
            "package/data/LEGITEXT000006072050.json": b"{}",
            "package/data/LEGITEXT000006073189.json": b"{}",
        }
    )
    manifest = fetch_npm(LocalStore(tmp_path), "legi", _registry(tarball))
    assert manifest is not None
    assert manifest.paths() == ["LEGITEXT000006072050.json"]


class FakeJudilibre:
    base_url = "https://judilibre.test"

    def __init__(self, decisions: dict[int, list[dict]] | None = None):
        self.decisions = decisions or {}
        self.calls: list[int] = []

    def get_decisions_between_dates(self, date_start: str, date_end: str):
        year = int(date_start[:4])
        self.calls.append(year)
        return self.decisions.get(year, [{"id": str(year)}])


def _decision(id: str, date: str = "2025-01-01") -> dict:
    return {"id": id, "decision_date": date}


def _fetch_judilibre(store: LocalStore, client: FakeJudilibre, day: int, **kwargs):
    return fetch_judilibre(
        store,
        cast(JudilibreClient, client),
        start_year=kwargs.pop("start_year", 2024),
        now=datetime(2026, 10, day, tzinfo=UTC),
        **kwargs,
    )


def _years(path: Path) -> list[str]:
    return [d["id"] for d in json.loads(path.read_text())]


def test_fetch_judilibre(tmp_path: Path):
    store = LocalStore(tmp_path)
    client = FakeJudilibre()

    manifest = _fetch_judilibre(store, client, 23)
    assert manifest is not None
    assert manifest.snapshot_id == "20261023"
    assert manifest.paths() == ["2024.json", "2025.json", "2026.json"]
    assert manifest.upstream["mode"] == "full"
    path = store.fetch_file(manifest, "2025.json")
    assert json.loads(path.read_text()) == [{"id": "2025"}]

    assert _fetch_judilibre(store, client, 23) is None


def test_judilibre_refresh_downloads_the_last_years_only(tmp_path: Path):
    store = LocalStore(tmp_path)
    first = _fetch_judilibre(store, FakeJudilibre(), 23)
    assert first is not None

    client = FakeJudilibre({2025: [_decision("2025"), _decision("late")]})
    second = _fetch_judilibre(store, client, 24)

    assert second is not None
    # last year and this year downloaded, 2024 carried over
    assert client.calls == [2025, 2026]
    assert second.paths() == ["2024.json", "2025.json", "2026.json"]
    assert second.upstream["mode"] == "window"
    assert second.upstream["fetched_years"] == [2025, 2026]
    assert second.upstream["carried_from"] == "20261023"
    sha = {f.path: f.sha256 for f in first.files}
    assert {f.path: f.sha256 for f in second.files}["2024.json"] == sha["2024.json"]
    assert _years(store.fetch_file(second, "2025.json")) == ["2025", "late"]
    assert store.latest("judilibre") == "20261024"


def test_judilibre_refresh_since_year(tmp_path: Path):
    store = LocalStore(tmp_path)
    assert _fetch_judilibre(store, FakeJudilibre(), 23) is not None

    client = FakeJudilibre({2026: [_decision("new", "2026-10-01")]})
    assert _fetch_judilibre(store, client, 24, since_year=2026) is not None
    assert client.calls == [2026]


def test_judilibre_refresh_without_changes_is_a_no_op(tmp_path: Path):
    store = LocalStore(tmp_path)
    assert _fetch_judilibre(store, FakeJudilibre(), 23) is not None

    assert _fetch_judilibre(store, FakeJudilibre(), 24) is None
    assert store.latest("judilibre") == "20261023"
    assert not store.exists("judilibre", "20261024")


def test_judilibre_full_downloads_every_year(tmp_path: Path):
    store = LocalStore(tmp_path)
    assert _fetch_judilibre(store, FakeJudilibre(), 23) is not None

    client = FakeJudilibre({2024: [_decision("2024"), _decision("edited")]})
    second = _fetch_judilibre(store, client, 24, full=True)
    assert second is not None
    assert client.calls == [2024, 2025, 2026]
    assert second.upstream["mode"] == "full"


def test_judilibre_refresh_leaves_no_gap(tmp_path: Path):
    store = LocalStore(tmp_path)
    # a snapshot made in 2024 only holds 2024
    old = fetch_judilibre(
        store,
        cast(JudilibreClient, FakeJudilibre()),
        start_year=2024,
        now=datetime(2024, 6, 1, tzinfo=UTC),
    )
    assert old is not None and old.paths() == ["2024.json"]

    client = FakeJudilibre()
    refreshed = _fetch_judilibre(store, client, 24)
    assert refreshed is not None
    # "last year" would be 2025: 2024 is downloaded again to keep the years contiguous
    assert client.calls == [2024, 2025, 2026]


def test_judilibre_shrink_guard(tmp_path: Path):
    store = LocalStore(tmp_path)
    many = [_decision(f"d{i}") for i in range(100)]
    assert _fetch_judilibre(store, FakeJudilibre({2025: many}), 23) is not None

    few = FakeJudilibre({2025: many[:50]})
    with pytest.raises(SnapshotError, match="2025: 100 -> 50"):
        _fetch_judilibre(store, few, 24)
    assert store.latest("judilibre") == "20261023"

    accepted = _fetch_judilibre(store, few, 24, allow_shrink=True)
    assert accepted is not None
    assert len(_years(store.fetch_file(accepted, "2025.json"))) == 50


def test_judilibre_files_are_sorted_and_deduplicated(tmp_path: Path):
    store = LocalStore(tmp_path)
    client = FakeJudilibre(
        {
            2024: [
                _decision("b", "2024-02-01"),
                _decision("a", "2024-01-01"),
                _decision("b", "2024-02-01"),
            ]
        }
    )
    manifest = _fetch_judilibre(store, client, 23)
    assert manifest is not None
    assert _years(store.fetch_file(manifest, "2024.json")) == ["a", "b"]


def test_import_judilibre_dir(tmp_path: Path):
    by_year = {
        2023: [_decision("a", "2023-01-01"), _decision("b", "2023-02-01")],
        2024: [_decision("c", "2024-01-01")],
        2025: [_decision("d", "2025-01-01")],
    }
    directory = tmp_path / "judilibre"
    directory.mkdir()
    for year, decisions in by_year.items():
        # unsorted, with a repeated decision
        (directory / f"{year}.json").write_text(json.dumps(decisions[::-1] * 2))
    (directory / "notes.json").write_text("{}")
    store = LocalStore(tmp_path / "store")
    now = datetime(2026, 10, 23, tzinfo=UTC)

    manifest = import_dir(store, "judilibre", directory, now=now)
    assert manifest is not None
    assert manifest.snapshot_id.startswith("20261023-local.")
    assert manifest.paths() == ["2023.json", "2024.json", "2025.json"]
    assert _years(store.fetch_file(manifest, "2023.json")) == ["a", "b"]
    assert import_dir(store, "judilibre", directory, now=now) is None

    # the next API refresh builds on the imported snapshot
    client = FakeJudilibre(by_year)
    refreshed = _fetch_judilibre(store, client, 24, start_year=2023)
    assert refreshed is not None
    assert client.calls == [2025, 2026]
    assert refreshed.upstream["carried_from"] == manifest.snapshot_id
    assert refreshed.paths() == manifest.paths() + ["2026.json"]


def _kali_checkout(root: Path) -> Path:
    data = root / "kali-data" / "data"
    data.mkdir(parents=True)
    (root / "kali-data" / "package.json").write_text('{"version": "3.473.0"}')
    (data / "index.json").write_text("[]")
    (data / "KALICONT000000000001.json").write_text('{"children": [{"data": {}}]}')
    (data / "KALICONT000000000002.json").write_text('{"data": {"num": 2}}')
    return data


def test_import_dir(tmp_path: Path):
    store = LocalStore(tmp_path / "store")
    data = _kali_checkout(tmp_path)

    manifest = import_dir(store, "kali", data)
    assert manifest is not None
    assert manifest.snapshot_id.startswith("3.473.0-local.")
    assert manifest.paths() == [
        "KALICONT000000000001.json",
        "KALICONT000000000002.json",
    ]
    assert manifest.upstream["empty_agreements"] == 1
    assert store.latest("kali") == manifest.snapshot_id

    # unchanged content: no new snapshot; changed content: a new id
    assert import_dir(store, "kali", data) is None
    (data / "KALICONT000000000002.json").write_text('{"children": [{}]}')
    changed = import_dir(store, "kali", data)
    assert changed is not None
    assert changed.snapshot_id != manifest.snapshot_id
    assert changed.upstream["empty_agreements"] == 0


def test_import_dir_without_data_files(tmp_path: Path):
    with pytest.raises(SnapshotError, match="No legi data file"):
        import_dir(LocalStore(tmp_path / "store"), "legi", _kali_checkout(tmp_path))
