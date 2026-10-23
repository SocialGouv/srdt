from datetime import date, timedelta
from typing import Any

import pytest

from ingestion.sources import judilibre
from ingestion.sources.judilibre import JudilibreClient, JudilibreError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None):
        self.status_code = status_code
        self.payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeApi:
    """Judilibre search over a fixed list of decisions."""

    def __init__(self, decisions: list[dict], unstable: bool = False):
        self.decisions = decisions
        self.unstable = unstable
        self.requests: list[dict] = []

    def get(self, url, headers, params, timeout):
        self.requests.append(params)
        found = [
            d
            for d in self.decisions
            if params["date_start"] <= d["decision_date"] <= params["date_end"]
        ]
        start = params["page"] * params["page_size"]
        results = found[start : start + params["page_size"]]
        if self.unstable and params["page"] == 1:
            # repeats the last decision of page 0, skips the first of page 1
            size = params["page_size"]
            results = [found[start - 1]] + found[start + 1 : start + size]
        return FakeResponse(200, {"total": len(found), "results": results})


def _decisions(count: int, first_day: date, per_day: int) -> list[dict]:
    return [
        {
            "id": f"d{i}",
            "number": f"n{i}",
            "decision_date": (first_day + timedelta(days=i // per_day)).isoformat(),
        }
        for i in range(count)
    ]


def _client(monkeypatch, api: FakeApi) -> JudilibreClient:
    monkeypatch.setattr(judilibre.requests, "get", api.get)
    monkeypatch.setattr(judilibre.time, "sleep", lambda _: None)
    return JudilibreClient("key")


def test_a_window_that_fits_one_page_is_read_in_one_request(monkeypatch):
    api = FakeApi(_decisions(20, date(2025, 1, 1), per_day=2))
    client = _client(monkeypatch, api)

    found = client.get_decisions_between_dates("2025-01-01", "2025-12-31")
    assert [d["id"] for d in found] == [f"d{i}" for i in range(20)]
    assert len(api.requests) == 1


def test_a_big_window_is_split_without_walking_pages(monkeypatch):
    api = FakeApi(_decisions(187, date(2025, 1, 1), per_day=1))
    client = _client(monkeypatch, api)

    found = client.get_decisions_between_dates("2025-01-01", "2025-12-31")
    assert sorted(d["id"] for d in found) == sorted(f"d{i}" for i in range(187))
    assert {r["page"] for r in api.requests} == {0}


def test_a_day_bigger_than_a_page_is_paginated_and_checked(monkeypatch):
    api = FakeApi(_decisions(120, date(2025, 3, 3), per_day=1000))
    client = _client(monkeypatch, api)

    found = client.get_decisions_between_dates("2025-03-03", "2025-03-03")
    assert len({d["id"] for d in found}) == 120

    unstable = FakeApi(_decisions(120, date(2025, 3, 3), per_day=1000), unstable=True)
    with pytest.raises(JudilibreError, match="unstable"):
        _client(monkeypatch, unstable)._window(date(2025, 3, 3), date(2025, 3, 3))


def test_missing_decisions_are_an_error(monkeypatch):
    def get(url, headers, params, timeout):
        return FakeResponse(200, {"total": 3, "results": [{"id": "a"}, {"id": "b"}]})

    monkeypatch.setattr(judilibre.requests, "get", get)
    monkeypatch.setattr(judilibre.time, "sleep", lambda _: None)
    with pytest.raises(JudilibreError, match="2 decisions returned of 3"):
        JudilibreClient("key")._window(date(2025, 1, 1), date(2025, 1, 31))


def test_an_empty_window(monkeypatch):
    client = _client(monkeypatch, FakeApi([]))
    assert client.get_decisions_between_dates("2025-01-01", "2025-01-31") == []


def test_pagination_window_end(monkeypatch):
    monkeypatch.setattr(judilibre.requests, "get", lambda *a, **k: FakeResponse(416))
    monkeypatch.setattr(judilibre.time, "sleep", lambda _: None)
    assert (
        JudilibreClient("key").get_decisions_between_dates("2025-01-01", "2025-01-31")
        == []
    )
