"""Compare the stored rankings with what the web app actually retrieves.

Two steps, so that the calls are made once and the comparison can be redone offline:

- `snapshot_queries` calls the web `POST /api/generate` (the production path: anonymize,
  IDCC, fiches, code du travail, jurisprudence, then the LLM answer) and saves the whole
  response; then runs the Python port (`pipeline.rank_query`) on the text the web
  searched, right after, so that both see the same index and reranker.
- `check_snapshot` reads those files and the stored run, and makes no call.

A port-only snapshot (`snapshot_port_only`) skips the web: it asks the API's
`/anonymize` for the text, as the web does, and runs the port on it. No LLM call, so it
is cheap enough for every query; it has no parity, only drift (port vs the stored run,
or vs the port rankings of another snapshot). Its compare lines keep the `web_*` keys,
filled from the port.

runs/<run_id>/web_snapshots/<timestamp>/
    meta.json          when, against which URLs, for which queries
    responses.jsonl    the entire web response per query
    port.jsonl         the port's hybrid+rerank ranking per query
    compare.jsonl      written by `check_snapshot`, one line per query
    report.md          idem
    compare-vs-<snapshot>.jsonl, report-vs-<snapshot>.md
                       idem, against another snapshot (`--against`)

What is compared, per query:
- parity (web vs port, same minute): the ordered top K_RERANK fiches, the decision to
  add the generic `contributions` collection;
- drift (web vs the stored hybrid+rerank ranking, or vs another snapshot);
- whether `/anonymize` changed the stored query text (the stored run then searched
  another text than production): drift is counted on the other queries only.
Jurisprudence is saved and listed, not scored: the web filters it with an LLM.
"""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from retrieval_eval.data import Query, Ranking, load_queries, load_rankings
from retrieval_eval.jsonl import append_jsonl, read_jsonl
from retrieval_eval.pipeline import (
    CONTENT_COLLECTIONS,
    GENERIC_CONTRIBUTIONS,
    K_RERANK,
    rank_query,
)
from retrieval_eval.search_client import RETRYABLE_STATUS, SearchAPI, SearchAPIError

SNAPSHOTS_DIR = "web_snapshots"
META_FILE = "meta.json"
RESPONSES_FILE = "responses.jsonl"
PORT_FILE = "port.jsonl"
COMPARE_FILE = "compare.jsonl"
REPORT_FILE = "report.md"


def output_files(against: Path | None) -> tuple[str, str]:
    """compare/report file names: a comparison with another snapshot gets its own,
    so that it does not overwrite the comparison with the stored run."""
    if against is None:
        return COMPARE_FILE, REPORT_FILE
    return f"compare-vs-{against.name}.jsonl", f"report-vs-{against.name}.md"


VARIANT = "hybrid+rerank"  # what production does

FICHE_SOURCES = frozenset((*CONTENT_COLLECTIONS, GENERIC_CONTRIBUTIONS))
CODE_SOURCE = "code_du_travail"  # web: Collection.CODE_DU_TRAVAIL
JURISPRUDENCE_SOURCE = "judilibre"  # web: Collection.JUDILIBRE


class WebAPIError(RuntimeError):
    pass


class WebResponse(BaseModel):
    """One call of `/api/generate`; `response` is the body exactly as returned."""

    query_id: str
    question: str
    idcc: str | None = None
    status_code: int | None = None
    latency_s: float | None = None
    error: str | None = None
    response: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return bool(self.response and self.response.get("success"))


class PortRanking(Ranking):
    """The port's ranking, with the text it searched (the web's anonymized text)."""

    text: str


class WebClient:
    def __init__(
        self,
        base_url: str,
        debug_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 300,
        max_retries: int = 1,
        backoff_s: float = 2.0,
    ):
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_s
        )
        self._headers = {"Authorization": f"Bearer {debug_key}"}
        self._max_retries = max_retries
        self._backoff_s = backoff_s

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(self, query: Query) -> WebResponse:
        """`/api/generate` as the web page calls it for a first question; the
        jurisprudence is left at its default (included). Errors are recorded, not
        raised: the response of a failed generation is worth keeping too."""
        body: dict[str, Any] = {"question": query.text}
        if query.idcc:
            body["agreementId"] = query.idcc
        record = WebResponse(
            query_id=query.query_id, question=query.text, idcc=query.idcc
        )
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(self._backoff_s * 2 ** (attempt - 1))
            start = time.monotonic()
            try:
                response = await self._client.post(
                    "/api/generate", json=body, headers=self._headers
                )
            except httpx.TransportError as e:
                record.error = f"{type(e).__name__}: {e}"
                continue
            record.latency_s = round(time.monotonic() - start, 2)
            record.status_code = response.status_code
            if response.status_code == 401:
                raise WebAPIError(
                    "POST /api/generate: HTTP 401, DEBUG_API_KEY is not the web's"
                )
            try:
                record.response = response.json()
            except ValueError:
                record.response = None
            if record.ok:
                record.error = None
                return record
            record.error = (record.response or {}).get("error") or response.text[:300]
            if response.status_code not in RETRYABLE_STATUS:
                break
        return record


# --- reading a response --------------------------------------------------------


def web_chunks(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not response:
        return []
    return (response.get("data") or {}).get("localSearchChunks") or []


def _source(chunk: dict[str, Any]) -> str:
    return (chunk.get("metadata") or {}).get("source", "")


def fiche_ids(chunks: list[dict[str, Any]]) -> list[str]:
    """The documents of `searchTextContent`, in the web's order (rerank order)."""
    return [c["metadata"]["id"] for c in chunks if _source(c) in FICHE_SOURCES]


def code_ids(chunks: list[dict[str, Any]]) -> list[str]:
    return [c["metadata"]["id"] for c in chunks if _source(c) == CODE_SOURCE]


def idcc_count(chunks: list[dict[str, Any]]) -> int:
    """Chunks of the IDCC pipeline: everything that is not a fiche, an article or a
    decision (`conventions`, `contributions_idcc`)."""
    known = FICHE_SOURCES | {CODE_SOURCE, JURISPRUDENCE_SOURCE}
    return sum(1 for c in chunks if _source(c) not in known)


def jurisprudence(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The decisions kept by the web (after rerank and the LLM filter), in order."""
    return [
        {
            "id": c["metadata"].get("id"),
            "id_chunk": c.get("id_chunk"),
            "title": c["metadata"].get("title", ""),
            "rerank_score": c.get("rerank_score"),
        }
        for c in chunks
        if _source(c) == JURISPRUDENCE_SOURCE
    ]


def anonymized_text(record: WebResponse) -> str:
    data = (record.response or {}).get("data") or {}
    return (data.get("anonymized") or {}).get("anonymized_question") or record.question


# --- comparing -----------------------------------------------------------------


def compare_lists(reference: list[str], other: list[str]) -> dict[str, Any]:
    """How `other` differs from `reference` (both cut at K_RERANK)."""
    a, b = reference[:K_RERANK], other[:K_RERANK]
    first_diff = next(
        (i + 1 for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y),
        None if len(a) == len(b) else min(len(a), len(b)) + 1,
    )
    common = set(a) & set(b)
    return {
        "identical": a == b,
        "same_set": set(a) == set(b),
        "first_diff": first_diff,  # 1-based rank, None when identical
        "overlap": len(common) / K_RERANK,
        "gained": [d for d in b if d not in common],
        "lost": [d for d in a if d not in common],
    }


def compare(
    query: Query | None,
    web: WebResponse,
    stored: Ranking | None,
    port: PortRanking | None,
) -> dict[str, Any]:
    """One line of compare.jsonl. `contributions` is True when the web kept no IDCC
    chunk, as in `prepareQuestionData`."""
    chunks = web_chunks(web.response)
    fiches = fiche_ids(chunks)
    n_idcc = idcc_count(chunks)
    web_contributions = n_idcc < 1
    line: dict[str, Any] = {
        "query_id": web.query_id,
        "web_ok": web.ok,
        "error": web.error,
        "anonymize_changed": (
            query is not None and web.ok and anonymized_text(web) != query.text
        ),
        "web_fiches": fiches,
        "web_contributions": web_contributions,
        "web_idcc_chunks": n_idcc,
        "web_code_du_travail": code_ids(chunks),
        "web_jurisprudence": jurisprudence(chunks),
        "parity": None,
        "drift": None,
    }
    if not web.ok:
        return line
    if port is not None:
        line["parity"] = compare_lists(port.doc_ids, fiches) | {
            "contributions_equal": port.contributions == web_contributions,
            "port_top": port.doc_ids[:K_RERANK],
        }
    if stored is not None:
        line["drift"] = compare_lists(stored.doc_ids, fiches) | {
            "contributions_equal": stored.contributions == web_contributions,
            "stored_top": stored.doc_ids[:K_RERANK],
        }
    return line


def compare_snapshots(base: WebResponse, new: WebResponse) -> dict[str, Any]:
    """Drift between two web snapshots of a query (fiches, IDCC, jurisprudence)."""
    a, b = web_chunks(base.response), web_chunks(new.response)
    juris_a = [(j["id"], j["id_chunk"]) for j in jurisprudence(a)]
    juris_b = [(j["id"], j["id_chunk"]) for j in jurisprudence(b)]
    return {
        "query_id": new.query_id,
        "web_ok": base.ok and new.ok,
        "error": new.error or base.error,
        "anonymize_changed": anonymized_text(base) != anonymized_text(new),
        "web_fiches": fiche_ids(b),
        "web_contributions": idcc_count(b) < 1,
        "web_idcc_chunks": idcc_count(b),
        "web_code_du_travail": code_ids(b),
        "web_jurisprudence": jurisprudence(b),
        "parity": None,
        "drift": compare_lists(fiche_ids(a), fiche_ids(b))
        | {
            "contributions_equal": (idcc_count(a) < 1) == (idcc_count(b) < 1),
            "code_du_travail_equal": code_ids(a) == code_ids(b),
            "jurisprudence_equal": juris_a == juris_b,
        },
    }


# --- files ---------------------------------------------------------------------


def snapshot_root(run_dir: Path) -> Path:
    return run_dir / SNAPSHOTS_DIR


def new_snapshot_dir(run_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return snapshot_root(run_dir) / stamp


def find_snapshot(run_dir: Path, name: str | None = None) -> Path:
    """The named snapshot, or the latest one."""
    root = snapshot_root(run_dir)
    if name:
        path = root / name
        if not path.is_dir():
            raise FileNotFoundError(f"{path} not found")
        return path
    found = sorted(
        p
        for p in root.glob("*")
        if (p / RESPONSES_FILE).exists() or (p / PORT_FILE).exists()
    )
    if not found:
        raise FileNotFoundError(f"no snapshot under {root}: run `web-snapshot` first")
    return found[-1]


def load_responses(path: Path) -> dict[str, WebResponse]:
    """Latest response per query (a retried query appends a new line)."""
    return {r.query_id: r for r in read_jsonl(path, WebResponse)}


def load_port(path: Path) -> dict[str, PortRanking]:
    return {r.query_id: r for r in read_jsonl(path, PortRanking)}


# --- snapshot (calls) ----------------------------------------------------------


@dataclass
class SnapshotSummary:
    called: int = 0
    skipped: int = 0
    web_failed: dict[str, str] = field(default_factory=dict)  # query_id -> error
    port_failed: dict[str, str] = field(default_factory=dict)


def write_meta(snapshot_dir: Path, meta: dict[str, Any]) -> None:
    """Create meta.json; a resumed snapshot keeps its creation date and gains the
    query ids of the new call."""
    path = snapshot_dir / META_FILE
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        meta = existing | {
            "query_ids": sorted(set(existing["query_ids"]) | set(meta["query_ids"]))
        }
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


async def snapshot_queries(
    web: WebClient,
    api: SearchAPI | None,
    queries: list[Query],
    snapshot_dir: Path,
    *,
    concurrency: int = 2,
    on_progress: Callable[[int, int], None] | None = None,
) -> SnapshotSummary:
    """Web call then port call for each query; `api=None` skips the port.

    Resumable: a query whose web response succeeded is not called again, and only
    its missing port ranking is computed."""
    responses_path = snapshot_dir / RESPONSES_FILE
    port_path = snapshot_dir / PORT_FILE
    responses = load_responses(responses_path)
    ported = set(load_port(port_path))
    summary = SnapshotSummary()
    todo = [
        q
        for q in queries
        if not (
            q.query_id in responses
            and responses[q.query_id].ok
            and (api is None or q.query_id in ported)
        )
    ]
    summary.skipped = len(queries) - len(todo)

    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    finished = 0

    async def one(query: Query) -> None:
        nonlocal finished
        async with semaphore:
            record = responses.get(query.query_id)
            if record is None or not record.ok:
                record = await web.generate(query)
                async with lock:
                    append_jsonl(responses_path, [record])
                summary.called += 1
            if not record.ok:
                summary.web_failed[query.query_id] = record.error or "no response"
            elif api is not None:
                text = anonymized_text(record)
                try:
                    (ranking,) = await rank_query(
                        api, query.model_copy(update={"text": text}), [VARIANT]
                    )
                except SearchAPIError as e:
                    summary.port_failed[query.query_id] = str(e)
                else:
                    async with lock:
                        append_jsonl(
                            port_path,
                            [PortRanking(**ranking.model_dump(), text=text)],
                        )
        async with lock:
            finished += 1
            if on_progress:
                on_progress(finished, len(todo))

    await asyncio.gather(*(one(q) for q in todo))
    return summary


async def snapshot_port_only(
    api: SearchAPI,
    queries: list[Query],
    snapshot_dir: Path,
    *,
    concurrency: int = 4,
    on_progress: Callable[[int, int], None] | None = None,
) -> SnapshotSummary:
    """`/anonymize` then the port, for each query not yet in port.jsonl."""
    port_path = snapshot_dir / PORT_FILE
    ported = set(load_port(port_path))
    summary = SnapshotSummary()
    todo = [q for q in queries if q.query_id not in ported]
    summary.skipped = len(queries) - len(todo)

    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    finished = 0

    async def one(query: Query) -> None:
        nonlocal finished
        async with semaphore:
            try:
                text = await api.anonymize(query.text)
                (ranking,) = await rank_query(
                    api, query.model_copy(update={"text": text}), [VARIANT]
                )
            except SearchAPIError as e:
                summary.port_failed[query.query_id] = str(e)
            else:
                async with lock:
                    append_jsonl(
                        port_path, [PortRanking(**ranking.model_dump(), text=text)]
                    )
                summary.called += 1
        async with lock:
            finished += 1
            if on_progress:
                on_progress(finished, len(todo))

    await asyncio.gather(*(one(q) for q in todo))
    return summary


# --- check (no call) -----------------------------------------------------------


def port_line(
    port: PortRanking, drift: dict[str, Any] | None, anonymize_changed: bool
) -> dict[str, Any]:
    """A compare line for a port-only snapshot, with the keys of `compare`."""
    return {
        "query_id": port.query_id,
        "web_ok": True,
        "error": None,
        "anonymize_changed": anonymize_changed,
        "web_fiches": port.doc_ids[:K_RERANK],
        "web_contributions": port.contributions,
        "web_idcc_chunks": None,
        "web_code_du_travail": [],
        "web_jurisprudence": [],
        "parity": None,
        "drift": drift,
    }


def compare_port(
    query: Query | None, port: PortRanking, stored: Ranking | None
) -> dict[str, Any]:
    drift = None
    if stored is not None:
        drift = compare_lists(stored.doc_ids, port.doc_ids) | {
            "contributions_equal": stored.contributions == port.contributions,
            "stored_top": stored.doc_ids[:K_RERANK],
        }
    return port_line(port, drift, query is not None and port.text != query.text)


def compare_ports(base: PortRanking, new: PortRanking) -> dict[str, Any]:
    drift = compare_lists(base.doc_ids, new.doc_ids) | {
        "contributions_equal": base.contributions == new.contributions,
    }
    return port_line(new, drift, base.text != new.text)


def check_snapshot(
    snapshot_dir: Path,
    *,
    queries_path: Path,
    rankings_path: Path | None,
    against: Path | None = None,
) -> list[dict[str, Any]]:
    """Compare a snapshot with the stored run (`rankings_path`) or, with `against`,
    with an earlier snapshot. Reads files only. Writes compare.jsonl and report.md
    into `snapshot_dir`."""
    responses = load_responses(snapshot_dir / RESPONSES_FILE)
    port = load_port(snapshot_dir / PORT_FILE)
    if not responses and not port:
        raise FileNotFoundError(f"{snapshot_dir}: no web response nor port ranking")
    queries = {q.query_id: q for q in load_queries(queries_path)}
    lines: list[dict[str, Any]] = []
    if against is not None:
        base = load_responses(against / RESPONSES_FILE)
        if responses and base:  # two web snapshots: compare what the web retrieved
            for query_id, new in responses.items():
                if query_id in base:
                    lines.append(compare_snapshots(base[query_id], new))
        else:  # a port-only snapshot on either side: compare the port rankings
            base_port = load_port(against / PORT_FILE)
            for query_id, new_port in port.items():
                if query_id in base_port:
                    lines.append(compare_ports(base_port[query_id], new_port))
    else:
        stored: dict[str, Ranking] = {}
        if rankings_path is not None and rankings_path.exists():
            stored = {
                r.query_id: r
                for r in load_rankings(rankings_path)
                if r.variant == VARIANT
            }
        if responses:
            for query_id, web in responses.items():
                lines.append(
                    compare(
                        queries.get(query_id),
                        web,
                        stored.get(query_id),
                        port.get(query_id),
                    )
                )
        else:
            for query_id, ported in port.items():
                lines.append(
                    compare_port(queries.get(query_id), ported, stored.get(query_id))
                )

    compare_file, report_file = output_files(against)
    compare_path = snapshot_dir / compare_file
    compare_path.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
        encoding="utf-8",
    )
    if against is not None:
        title = f"{snapshot_dir.name} vs snapshot {against.name}"
    else:
        stored_run = rankings_path.parent.name if rankings_path else "no stored run"
        title = f"{snapshot_dir.name} vs {stored_run}"
    (snapshot_dir / report_file).write_text(
        render_report(lines, title), encoding="utf-8"
    )
    return lines


def _mark(value: bool | None) -> str:
    return "-" if value is None else ("ok" if value else "DIFF")


def _stats(name: str, checked: list[dict[str, Any]]) -> str:
    identical = sum(c["identical"] and c["contributions_equal"] for c in checked)
    same_set = sum(c["same_set"] for c in checked)
    overlap = sum(c["overlap"] for c in checked) / len(checked)
    return (
        f"{name}: {identical}/{len(checked)} identical top {K_RERANK} "
        f"(+contributions), {same_set}/{len(checked)} same set, "
        f"mean overlap@{K_RERANK} {overlap:.2f}"
    )


def summary_lines(lines: list[dict[str, Any]]) -> list[str]:
    """Drift is counted on the queries whose text `/anonymize` left as stored: on the
    others the two sides searched different texts, so their drift is listed apart."""
    ok = [line for line in lines if line["web_ok"]]
    out = [f"{len(ok)}/{len(lines)} queries usable (web call or port ran)"]
    parity = [line["parity"] for line in ok if line["parity"] is not None]
    if parity:
        out.append(_stats("parity", parity))
    drifted = [line for line in ok if line["drift"] is not None]
    same_text = [line["drift"] for line in drifted if not line["anonymize_changed"]]
    if same_text:
        out.append(_stats("drift (same text)", same_text))
    changed = [line["query_id"] for line in drifted if line["anonymize_changed"]]
    if changed:
        out.append(
            f"anonymize changed the text of {len(changed)} queries, drift not counted: "
            + ", ".join(changed)
        )
    return out


def render_report(lines: list[dict[str, Any]], title: str) -> str:
    rows = [
        f"# Web check: {title}",
        "",
        *[f"- {line}" for line in summary_lines(lines)],
        "",
        "| query | parity | first diff | drift | first diff | overlap@10 "
        "| contributions | anonymize | jurisprudence |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for line in lines:
        if not line["web_ok"]:
            rows.append(
                f"| {line['query_id']} | web error: {line['error']} | | | | | | | |"
            )
            continue
        parity, drift = line["parity"], line["drift"]
        rows.append(
            "| {q} | {p} | {pf} | {d} | {df} | {ov} | {c} | {a} | {j} |".format(
                q=line["query_id"],
                p=_mark(
                    parity and parity["identical"] and parity["contributions_equal"]
                ),
                pf=(parity or {}).get("first_diff") or "",
                d=(
                    "text"
                    if drift and line["anonymize_changed"]
                    else _mark(
                        drift and drift["identical"] and drift["contributions_equal"]
                    )
                ),
                df=(drift or {}).get("first_diff") or "",
                ov=f"{drift['overlap']:.1f}" if drift else "",
                c="generic" if line["web_contributions"] else "idcc",
                a="changed" if line["anonymize_changed"] else "",
                j=len(line["web_jurisprudence"]),
            )
        )
    return "\n".join(rows) + "\n"


def has_parity_diff(lines: list[dict[str, Any]]) -> bool:
    return any(
        line["parity"] is not None
        and not (line["parity"]["identical"] and line["parity"]["contributions_equal"])
        for line in lines
    )


def has_drift(lines: list[dict[str, Any]]) -> bool:
    return any(
        line["drift"] is not None
        and not all(
            v for k, v in line["drift"].items() if k.endswith(("identical", "_equal"))
        )
        for line in lines
    )
