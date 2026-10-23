"""Cour de cassation decisions (chambre sociale, published in the bulletin) from
the PISTE Judilibre API: download, and chunking of their titles and summaries
(ported from the api's clients/judilibre_client.py and ingestion/judilibre.py)."""

import time
from datetime import date, timedelta

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from ingestion.contract import Chunk
from ingestion.text.chunker import Chunker

JUDILIBRE_BASE_URL = "https://api.piste.gouv.fr/cassation/judilibre/v1.0"

# Judilibre search filters
JURISDICTION = "cc"  # Cour de cassation
PUBLICATION = "b"  # published in the bulletin
CHAMBER = "soc"  # chambre sociale (labour law)


def get_decision_url(decision_id: str) -> str:
    return f"https://www.courdecassation.fr/decision/{decision_id}"


class JudilibreError(RuntimeError):
    pass


class JudilibreClient:
    def __init__(self, api_key: str, base_url: str = JUDILIBRE_BASE_URL):
        self.base_url = base_url
        self.batch_size = 50
        # pause between two requests
        self.delay = 1.0
        self.headers = {"accept": "application/json", "KeyId": api_key}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True,
    )
    def get_decisions_between_dates(self, date_start: str, date_end: str) -> list[dict]:
        """Decisions between two dates (YYYY-MM-DD, both included).

        Walking the pages of a big result is not reliable: decisions sharing a date
        come back in an unstable order, so a page can repeat a decision and skip
        another. A window whose `total` fits in one page is read in one request;
        a bigger one is split in two. Every window is checked against its `total`.
        """
        start, end = date.fromisoformat(date_start), date.fromisoformat(date_end)
        return self._window(start, end)

    def _window(self, start: date, end: date) -> list[dict]:
        first = self._search(start, end, page=0)
        total = first["total"]
        results = first["results"]

        if total <= self.batch_size:
            if len(results) != total:
                raise JudilibreError(
                    f"{len(results)} decisions returned of {total} between {start} "
                    f"and {end}"
                )
            return [_summary(d) for d in results]

        if start < end:
            middle = start + (end - start) // 2
            return self._window(start, middle) + self._window(
                middle + timedelta(days=1), end
            )
        return self._paginate_day(start, first)

    def _paginate_day(self, day: date, first: dict) -> list[dict]:
        """A single day with more decisions than a page: the only case left where
        pages have to be walked."""
        decisions = {d["id"]: d for d in first["results"]}
        page = 0
        while len(first["results"]) == self.batch_size:
            page += 1
            first = self._search(day, day, page)
            decisions |= {d["id"]: d for d in first["results"]}
        if len(decisions) != first["total"]:
            raise JudilibreError(
                f"{len(decisions)} decisions of {first['total']} on {day}: "
                "the pagination of the API is unstable"
            )
        return [_summary(d) for d in decisions.values()]

    def _search(self, start: date, end: date, page: int) -> dict:
        response = requests.get(
            f"{self.base_url}/search",
            headers=self.headers,
            params={
                "query": "*",
                "jurisdiction": JURISDICTION,
                "chamber": CHAMBER,
                "publication": PUBLICATION,
                "date_start": start.isoformat(),
                "date_end": end.isoformat(),
                "page_size": self.batch_size,
                "page": page,  # the API is 0-indexed
            },
            timeout=30,
        )
        time.sleep(self.delay)
        # 416 = past the pagination window allowed by the API
        if response.status_code == 416:
            return {"total": 0, "results": []}
        response.raise_for_status()
        data = response.json()
        return {"total": data.get("total", 0), "results": data.get("results", [])}


def _summary(d: dict) -> dict:
    return {
        "id": d.get("id"),
        "number": d.get("number"),
        "decision_date": d.get("decision_date"),
        "chamber": d.get("chamber"),
        "formation": d.get("formation"),
        "type": d.get("type"),
        "solution": d.get("solution"),
        "publication": d.get("publication"),
        "titlesAndSummaries": d.get("titlesAndSummaries"),
    }


def chunk_decision(decision, chunker: Chunker) -> list[Chunk]:
    chunks: list[Chunk] = []
    decision_id = decision.get("id")

    for ts_idx, ts in enumerate(decision.get("titlesAndSummaries") or []):
        summary = ts.get("summary")
        if not summary:
            continue

        titles = ts.get("titles") or []
        header = " > ".join(titles)
        content = f"{header}\n{summary}" if header else summary
        id = f"{decision_id}-{ts_idx}"

        for idx, split in enumerate(chunker.split_character_recursive(content)):
            chunks.append(
                Chunk.model_validate(
                    {
                        "content": split.page_content,
                        "id": id,
                        "metadata": {
                            "id": id,
                            "source": "judilibre",
                            "url": get_decision_url(decision_id),
                            "initial_id": decision_id,
                            "title": ",".join(titles)
                            if titles
                            else decision.get("number"),
                            "idx": idx,
                            "idcc": None,
                            "number": decision.get("number"),
                            "decision_date": decision.get("decision_date"),
                            "articles": [],
                        },
                    }
                )
            )

    return chunks
