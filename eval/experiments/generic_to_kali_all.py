"""All-pairs version of generic_to_kali.py, read per agreement.

For every (question, agreement) pair, the generic contribution is the query (two
variants, `full` and `title`), the search is run over that agreement's `conventions`
chunks (kNN, BM25, hybrid RRF) and the articles the editors linked in the agreement
contribution are the labels. For each search configuration and each k in 5, 7, 10, the
report counts how many labelled articles are among the first k articles, per agreement.

It reuses the functions of generic_to_kali.py and is run the same way:

    cd ingestion && SEARCH_HOSTNAME=http://localhost:9202 SEARCH_INDEX=chunks \
      SNAPSHOT_STORE=local .venv/bin/python ../eval/experiments/generic_to_kali_all.py
"""

import json
import sys
import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generic_to_kali import (  # noqa: E402
    METHODS,
    RUNS,
    VARIANTS,
    Search,
    build_labels,
    build_queries,
    check_no_label_in_queries,
    collapse,
    embed_queries,
    norm_idcc,
    rrf,
)
from ingestion.config import load_config  # noqa: E402
from ingestion.pipeline import Inputs  # noqa: E402
from ingestion.settings import Settings, secret  # noqa: E402
from ingestion.snapshots.store import make_store  # noqa: E402
from ingestion.sources.postgres import load_documents  # noqa: E402

KS = (5, 7, 10)
# `rerank` re-orders the hybrid candidates (the 64 chunks of the API search) with Albert
RERANK = "rerank"
CONFIGS = [(v, m) for v in VARIANTS for m in (*METHODS, RERANK)]
TOP_STORED = 10
EMBED_BATCH = 4
RERANK_CACHE = Path(__file__).resolve().parent / ".cache" / "rerank.json"
RERANK_MODEL = "openweight-rerank"  # ALBERT_RERANK_MODEL in the API
RERANK_MAX_CHARS = 8192  # the API cuts each document there


class Reranker:
    """Albert /v1/rerank, called as AlbertClient.rerank and the /rerank endpoint of the
    API do: the chunk contents cut at 8192 characters, sorted by relevance score."""

    def __init__(self, settings: Settings):
        settings.require("albert_endpoint", "albert_api_key")
        self.url = f"{settings.albert_endpoint}/v1/rerank"
        self.headers = {"Authorization": f"Bearer {secret(settings.albert_api_key)}"}
        self.http = httpx.Client(timeout=180)
        self.cache: dict[str, list[float]] = {}
        if RERANK_CACHE.exists():
            self.cache = json.loads(RERANK_CACHE.read_text())
        self.calls = 0

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        reraise=True,
    )
    def _scores(self, query: str, documents: list[str]) -> list[float]:
        response = self.http.post(
            self.url,
            headers=self.headers,
            json={"query": query, "documents": documents, "model": RERANK_MODEL},
        )
        response.raise_for_status()
        scores = [0.0] * len(documents)
        for item in response.json()["results"]:
            scores[item["index"]] = item["relevance_score"]
        return scores

    def rerank(self, query: str, hits: list[dict]) -> list[dict]:
        key = hashlib.sha256(
            "\n".join([RERANK_MODEL, query, *(h["chunk"] for h in hits)]).encode()
        ).hexdigest()
        if key not in self.cache:
            documents = [h["content"][:RERANK_MAX_CHARS] for h in hits]
            self.cache[key] = self._scores(query, documents)
            self.calls += 1
            if self.calls % 25 == 0:
                self.save()
        ordered = sorted(zip(self.cache[key], hits, strict=True), key=lambda x: -x[0])
        return [{**h, "rank": i, "score": s} for i, (s, h) in enumerate(ordered, 1)]

    def save(self) -> None:
        RERANK_CACHE.parent.mkdir(parents=True, exist_ok=True)
        RERANK_CACHE.write_text(json.dumps(self.cache))


def name(config: tuple[str, str]) -> str:
    return f"{config[0]} {config[1]}"


def find_pairs(docs) -> tuple[list[tuple], dict[str, int]]:
    generics: dict[str, list] = defaultdict(list)
    for d in docs["contributions"]:
        if d.document.get("content") and d.document.get("questionId"):
            generics[d.document["questionId"]].append(d)
    skipped = {"no generic": 0, "several generics": 0, "no content": 0}
    pairs = []
    for a in docs["contributions_idcc"]:
        if not a.document.get("content"):
            skipped["no content"] += 1
            continue
        found = generics.get(a.document.get("questionId"), [])
        if not found:
            skipped["no generic"] += 1
        elif len(found) > 1:
            skipped["several generics"] += 1
        else:
            pairs.append((found[0], a))
    return pairs, skipped


def main() -> None:
    if sys.argv[1:2] == ["--from"]:
        # rebuild report.md and the csv files of a finished run, without searching again
        out = Path(sys.argv[2])
        run = json.loads((out / "results.json").read_text())
        write_report(out, run["records"], run)
        print(f"report: {out / 'report.md'}")
        return
    settings = Settings()
    inputs = Inputs(
        store=make_store(settings, "local"),
        config=load_config(Path("config/local.toml")),
        settings=settings,
    )
    docs = load_documents(settings, ["contributions", "contributions_idcc"])
    pairs, skipped = find_pairs(docs)
    print(f"{len(pairs)} pairs, skipped rows: {skipped}")

    search = Search(settings)
    reranker = Reranker(settings)
    provenance = {**search.index_meta(), "kali_snapshot": inputs.manifest("kali").snapshot_id}
    indexed = provenance["sources"]["conventions"]["snapshots"]["kali"]
    if indexed != provenance["kali_snapshot"]:
        sys.exit(f"index built from KALI {indexed}, labels from {provenance['kali_snapshot']}")

    # one query pair per generic: the embeddings do not depend on the agreement
    queries_by_generic = {g.cdtn_id: build_queries(g) for g in {g.cdtn_id: g for g, _ in pairs}.values()}
    flat = {f"{cid}:{v}": text for cid, qs in queries_by_generic.items() for v, text in qs.items()}
    # small batches: one request with every query is refused (413)
    vectors: dict[str, list[float]] = {}
    items = list(flat.items())
    for start in range(0, len(items), EMBED_BATCH):
        vectors |= embed_queries(settings, dict(items[start : start + EMBED_BATCH]))

    corpus: dict[str, tuple[int, int]] = {}
    records, failures = [], []
    for i, (generic, agreement) in enumerate(pairs, 1):
        idcc = norm_idcc(agreement.idcc)
        labels, dropped = build_labels(inputs, agreement)
        ids = sorted({label["chunk_id"] for label in labels})
        record = {
            "question": generic.title,
            "question_id": generic.document["questionId"],
            "idcc": idcc,
            "labels": ids,
            "dropped": len(dropped),
        }
        if not ids:
            record["status"] = "no label"
            records.append(record)
            continue
        queries = queries_by_generic[generic.cdtn_id]
        check_no_label_in_queries(queries, labels)
        try:
            if idcc not in corpus:
                corpus[idcc] = search.corpus(idcc)
            chunks, articles = corpus[idcc]
            if not chunks:
                raise RuntimeError("no conventions chunk (padding?)")
            record["articles"] = articles
            record["ranks"], record["top"] = {}, {}
            for v in VARIANTS:
                knn = search.knn(vectors[f"{generic.cdtn_id}:{v}"], idcc)
                bm25 = search.bm25(queries[v], idcc)
                hybrid = rrf(knn, bm25)
                for m, hits in (
                    ("knn", knn),
                    ("bm25", bm25),
                    ("hybrid", hybrid),
                    (RERANK, reranker.rerank(queries[v], hybrid)),
                ):
                    ranked = collapse(hits)
                    position = {h["article"]: h["rank"] for h in ranked}
                    key = f"{v} {m}"
                    record["ranks"][key] = {a: position.get(a) for a in ids}
                    record["top"][key] = [h["article"] for h in ranked[:TOP_STORED]]
            record["status"] = "ok"
        except Exception as e:  # keep going, report at the end
            record["status"] = f"failed: {e}"
            failures.append((idcc, generic.title[:40], str(e)[:120]))
        records.append(record)
        if i % 50 == 0:
            print(f"{i}/{len(pairs)}")

    reranker.save()
    out = RUNS / f"generic-to-kali-all-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    run = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": provenance,
        "skipped": skipped,
        "failures": failures,
        "records": records,
    }
    (out / "results.json").write_text(json.dumps(run, ensure_ascii=False, indent=1, default=str))
    write_report(out, records, run)
    print(f"report: {out / 'report.md'}")


# ---------------------------------------------------------------- metrics


def found_at(record: dict, config: tuple[str, str], k: int) -> int:
    ranks = record["ranks"][name(config)]
    return sum(1 for r in ranks.values() if r is not None and r <= k)


def agreements(records: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r["status"] == "ok":
            by[r["idcc"]].append(r)
    return dict(sorted(by.items(), key=lambda kv: int(kv[0] or 0)))


def expected_random(rs: list[dict], k: int) -> float:
    """Expected labelled articles found by a random top k, summed over pairs."""
    return sum(len(r["labels"]) * min(k, r["articles"]) / r["articles"] for r in rs)


def write_report(out: Path, records: list[dict], run: dict) -> None:
    ok = [r for r in records if r["status"] == "ok"]
    by = agreements(records)
    lines: list[str] = []
    add = lines.append
    add("# Generic contribution → agreement articles: all pairs, per agreement\n")
    prov = run["provenance"]
    add(f"Index `{prov['index']}`, KALI snapshot `{prov['kali_snapshot']}`, run {run['run_at']}.\n")
    add(f"- {len(records)} pairs; {len(ok)} scored, {sum(r['status'] == 'no label' for r in records)} "
        f"without a usable label, {len(run['failures'])} failed. Skipped rows: {run['skipped']}.")
    add(f"- {len(by)} agreements, {len({r['question_id'] for r in ok})} questions, "
        f"{sum(len(r['labels']) for r in ok)} labelled articles (distinct per pair).\n")
    add("A cell reads `found / labelled`: how many of the labelled articles of the agreement's "
        "pairs (each pair counted separately) are among the first k articles of that "
        "configuration. `random` is the expected count of a random top k.\n")

    add("## All agreements together\n")
    add("| configuration | " + " | ".join(f"k={k}" for k in KS) + " |")
    add("|---|" + "---|" * len(KS))
    total = sum(len(r["labels"]) for r in ok)
    for c in CONFIGS:
        cells = []
        for k in KS:
            f = sum(found_at(r, c, k) for r in ok)
            cells.append(f"{f} / {total} ({f / total:.0%})")
        add(f"| {name(c)} | " + " | ".join(cells) + " |")
    rand = [expected_random(ok, k) for k in KS]
    add("| random | " + " | ".join(f"{x:.0f} / {total} ({x / total:.0%})" for x in rand) + " |\n")

    for k in KS:
        add(f"## Per agreement, k = {k}\n")
        add("| IDCC | pairs | labelled | " + " | ".join(name(c) for c in CONFIGS) + " | random |")
        add("|---|---|---|" + "---|" * (len(CONFIGS) + 1))
        for idcc, rs in by.items():
            n = sum(len(r["labels"]) for r in rs)
            cells = [str(sum(found_at(r, c, k) for r in rs)) for c in CONFIGS]
            add(f"| {idcc} | {len(rs)} | {n} | " + " | ".join(cells)
                + f" | {expected_random(rs, k):.1f} |")
        add("")
    questions = by_question(records)
    add("## Per question (generic contribution)\n")
    add("Same counts, grouped by the generic contribution that is the query. The weakest "
        "questions (full semantic search, k=5) come first; a question has one query for all "
        "its agreements, so its pairs are not independent.\n")
    for k in KS:
        add(f"### Per question, k = {k}\n")
        add("| question | IDCC | labelled | per IDCC | " + " | ".join(name(c) for c in CONFIGS) + " | random |")
        add("|---|---|---|---|" + "---|" * (len(CONFIGS) + 1))
        for title, rs in questions:
            n = sum(len(r["labels"]) for r in rs)
            idccs = len({r["idcc"] for r in rs})
            cells = [str(sum(found_at(r, c, k) for r in rs)) for c in CONFIGS]
            add(f"| {title[:70]} | {idccs} | {n} | {n / idccs:.1f} | " + " | ".join(cells)
                + f" | {expected_random(rs, k):.1f} |")
        add("")
    if run["failures"]:
        add("## Failures\n")
        for idcc, title, err in run["failures"]:
            add(f"- IDCC {idcc}, {title}: {err}")
    (out / "report.md").write_text("\n".join(lines) + "\n")

    # the same numbers, for a spreadsheet
    rows = ["idcc,pairs,labelled,k,configuration,found,random"]
    for idcc, rs in by.items():
        n = sum(len(r["labels"]) for r in rs)
        for k in KS:
            for c in CONFIGS:
                rows.append(f"{idcc},{len(rs)},{n},{k},{name(c)},"
                            f"{sum(found_at(r, c, k) for r in rs)},{expected_random(rs, k):.2f}")
    (out / "per_agreement.csv").write_text("\n".join(rows) + "\n")

    rows = ["question,idcc,labelled,labels_per_idcc,k,configuration,found,random"]
    for title, rs in questions:
        n = sum(len(r["labels"]) for r in rs)
        idccs = len({r["idcc"] for r in rs})
        for k in KS:
            for c in CONFIGS:
                rows.append(f"\"{title}\",{idccs},{n},{n / idccs:.2f},{k},{name(c)},"
                            f"{sum(found_at(r, c, k) for r in rs)},{expected_random(rs, k):.2f}")
    (out / "per_question.csv").write_text("\n".join(rows) + "\n")


def by_question(records: list[dict]) -> list[tuple[str, list[dict]]]:
    """Scored pairs grouped by generic contribution, weakest first (full kNN, k=5)."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r["status"] == "ok":
            by[r["question"]].append(r)
    weak = ("full", "knn")
    return sorted(
        by.items(),
        key=lambda kv: sum(found_at(r, weak, 5) for r in kv[1])
        / sum(len(r["labels"]) for r in kv[1]),
    )


if __name__ == "__main__":
    main()
