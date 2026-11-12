"""Experiment: can a generic contribution find the agreement articles that the
editors linked in the agreement-specific contribution of the same question?

The query is built from the generic contribution (idcc 0000) only. The KALI links of the
agreement contribution (same `questionId`, given IDCC) are the labels and are only used
to score. The search is the API's hybrid search (exact kNN + BM25, RRF 60), run over the
`conventions` chunks of that agreement.

Read-only: reads Postgres, the KALI snapshot and Elasticsearch, calls Albert for the
embeddings of the queries (cached), writes to eval/runs/ only. It imports the ingestion
package without changing it, so run it with the ingestion virtualenv, from ingestion/:

    cd ingestion && SEARCH_HOSTNAME=http://localhost:9202 SEARCH_INDEX=chunks \
      SNAPSHOT_STORE=local .venv/bin/python ../eval/experiments/generic_to_kali.py \
      --question "Préavis de licenciement : est-il obligatoire" --idcc 2216
"""

import argparse
import difflib
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from ingestion.config import load_config
from ingestion.embed import AlbertEmbedder
from ingestion.index_writer import build_client
from ingestion.pipeline import Inputs
from ingestion.settings import Settings, secret
from ingestion.snapshots.store import make_store
from ingestion.sources.cdtn import PagesContributionsExploiter
from ingestion.sources.postgres import Document, load_documents

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent / "runs"
CACHE = HERE / ".cache" / "embeddings.json"

K = 64  # chunks kept per list, as `k_min` in the API search
RRF_CONSTANT = 60
EXACT_KNN_MAX_CHUNKS = 20_000  # above, the API switches to approximate kNN
TOP = 10  # articles shown per list
DIM = 1024
SNIPPET = 160

VARIANTS = ("full", "title")
METHODS = ("knn", "bm25", "hybrid")


def norm_idcc(idcc: str | None) -> str:
    return (idcc or "").lstrip("0")


def plain_text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


# ---------------------------------------------------------------- the pair


def pick_pair(
    settings: Settings, question: str, idcc: str
) -> tuple[Document, Document]:
    docs = load_documents(settings, ["contributions", "contributions_idcc"])
    generics = [d for d in docs["contributions"] if d.title.startswith(question)]
    if len(generics) != 1:
        titles = [d.title for d in generics]
        sys.exit(f"{len(generics)} generic contributions start with {question!r}: {titles}")
    generic = generics[0]
    siblings = [
        d
        for d in docs["contributions_idcc"]
        if d.document.get("questionId") == generic.document.get("questionId")
        and norm_idcc(d.idcc) == norm_idcc(idcc)
    ]
    if len(siblings) != 1:
        sys.exit(f"{len(siblings)} agreement contributions for IDCC {idcc} on this question")
    return generic, siblings[0]


def build_labels(inputs: Inputs, agreement: Document):
    """Resolved KALI links of the agreement contribution that a search over this
    agreement's conventions chunks can find, and the ones left out with the reason."""
    exploiter = PagesContributionsExploiter(kali_index=inputs.kali_index())
    kept, dropped = [], []
    for link in exploiter.extract_kali_links(agreement):
        if link["kind"] is None:
            reason = "not in the KALI snapshot"
        elif link["kind"] != "article":
            reason = "a section, not an article"
        elif not link["chunk_id"]:
            reason = "article without a conventions chunk"
        elif norm_idcc(link["idcc"]) != norm_idcc(agreement.idcc):
            reason = f"article of another agreement ({link['idcc']})"
        else:
            kept.append(link)
            continue
        dropped.append((reason, link))
    return kept, dropped


def build_queries(generic: Document) -> dict[str, str]:
    title = generic.title.strip()
    body = plain_text(generic.document["content"])
    return {"full": f"{title}\n\n{body}", "title": title}


def check_no_label_in_queries(queries: dict[str, str], labels: list[dict]):
    """The queries come from the generic contribution only; make sure no KALI id
    (hence no label) is in them."""
    for name, text in queries.items():
        assert "KALIARTI" not in text, f"{name} query contains a KALI id"
        for label in labels:
            assert label["kali_id"] not in text, f"{name} query contains a label"


def verbatim_overlap(generic: Document, agreement: Document) -> dict[str, int]:
    """How much of the agreement contribution is the generic answer, copied. Expected
    to be high (the agreement answer is written on top of the generic one); it is
    not a leak, the agreement text is never searched with, but it tells how much the
    two texts are alike."""
    a = plain_text(agreement.document["content"])
    g = plain_text(generic.document["content"])
    blocks = difflib.SequenceMatcher(None, a, g, autojunk=False).get_matching_blocks()
    copied = sum(b.size for b in blocks if b.size >= 40)
    return {"agreement_chars": len(a), "generic_chars": len(g), "copied_from_generic": copied}


# ---------------------------------------------------------------- embeddings


def embed_queries(settings: Settings, queries: dict[str, str]) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text())
    model = settings.albert_vectorisation_model or ""
    keys = {
        name: hashlib.sha256(f"{model}\n{text}".encode()).hexdigest()
        for name, text in queries.items()
    }
    missing = [n for n, k in keys.items() if k not in cache]
    if missing:
        vectors = AlbertEmbedder(settings, DIM).embed([queries[n] for n in missing])
        for name, vector in zip(missing, vectors, strict=True):
            cache[keys[name]] = vector
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
        print(f"embedded {len(missing)} queries with {model} (cached in {CACHE})")
    else:
        print("query embeddings read from the cache")
    return {name: cache[key] for name, key in keys.items()}


# ---------------------------------------------------------------- search


class Search:
    def __init__(self, settings: Settings):
        settings.require("search_hostname", "search_credentials")
        self.client = build_client(
            str(settings.search_hostname), secret(settings.search_credentials)
        )
        self.index = settings.search_index
        self.engine = settings.search_engine

    def index_meta(self) -> dict[str, Any]:
        (mapping,) = self.client.indices.get_mapping(index=self.index).items()
        return {"index": mapping[0], **mapping[1]["mappings"].get("_meta", {})}

    def filters(self, idcc: str) -> list[dict]:
        # conventions only (never contributions*), one agreement; idcc is unpadded
        return [
            {"term": {"metadata.source": "conventions"}},
            {"term": {"metadata.idcc": norm_idcc(idcc)}},
        ]

    def corpus(self, idcc: str) -> tuple[int, int]:
        body = {
            "size": 0,
            "query": {"bool": {"filter": self.filters(idcc)}},
            "track_total_hits": True,
            "aggs": {
                "articles": {
                    "cardinality": {
                        "field": "metadata.id.keyword",
                        "precision_threshold": 40_000,
                    }
                }
            },
        }
        r = self.client.search(index=self.index, body=body)
        return r["hits"]["total"]["value"], r["aggregations"]["articles"]["value"]

    def _hits(self, response: dict) -> list[dict]:
        hits = []
        for rank, h in enumerate(response["hits"]["hits"], 1):
            meta = h["_source"]["metadata"]
            assert meta["source"] == "conventions", meta["source"]
            hits.append(
                {
                    "rank": rank,
                    "chunk": h["_id"],
                    "article": meta["id"],
                    "title": meta["title"],
                    "idx": meta["idx"],
                    "score": h["_score"],
                    "content": h["_source"]["content"],
                }
            )
        return hits

    def knn(self, vector: list[float], idcc: str) -> list[dict]:
        filters = self.filters(idcc)
        n = self.client.count(
            index=self.index, body={"query": {"bool": {"filter": filters}}}
        )["count"]
        if n > EXACT_KNN_MAX_CHUNKS:
            raise RuntimeError(f"{n} chunks: the API would use approximate kNN here")
        field = "'embedding'" if self.engine == "elasticsearch" else "doc['embedding']"
        body = {
            "size": K,
            "_source": {"includes": ["content", "metadata"]},
            "query": {
                "script_score": {
                    "query": {
                        "bool": {
                            "filter": [*filters, {"exists": {"field": "embedding"}}]
                        }
                    },
                    "script": {
                        "source": f"(cosineSimilarity(params.query_vector, {field})"
                        " + 1.0) / 2.0",
                        "params": {"query_vector": vector},
                    },
                }
            },
        }
        return self._hits(self.client.search(index=self.index, body=body))

    def bm25(self, query: str, idcc: str) -> list[dict]:
        body = {
            "size": K,
            "_source": {"includes": ["content", "metadata"]},
            "query": {
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": self.filters(idcc),
                }
            },
        }
        return self._hits(self.client.search(index=self.index, body=body))

    def article_titles(self, idcc: str, ids: list[str]) -> dict[str, str]:
        body = {
            "size": 200,
            "_source": ["metadata.id", "metadata.title", "metadata.idx"],
            "query": {
                "bool": {
                    "filter": [
                        *self.filters(idcc),
                        {"terms": {"metadata.id.keyword": ids}},
                    ]
                }
            },
        }
        hits = self.client.search(index=self.index, body=body)["hits"]["hits"]
        return {h["_source"]["metadata"]["id"]: h["_source"]["metadata"]["title"] for h in hits}


def rrf(knn: list[dict], bm25: list[dict]) -> list[dict]:
    """The fusion of `SearchIndexHandler.search` (api/srdt_analysis/clients/
    search_handler.py): 1 / (rank + 60) summed over the two lists."""
    if not bm25:
        return knn[:K]
    by_chunk = {h["chunk"]: h for h in knn + bm25}
    score: dict[str, float] = defaultdict(float)
    for hits in (knn, bm25):
        for rank, h in enumerate(hits, 1):
            score[h["chunk"]] += 1 / (rank + RRF_CONSTANT)
    ordered = sorted(score.items(), key=lambda x: x[1], reverse=True)[:K]
    return [
        {**by_chunk[chunk], "rank": rank, "score": s}
        for rank, (chunk, s) in enumerate(ordered, 1)
    ]


def collapse(hits: list[dict]) -> list[dict]:
    """Ranked chunks -> ranked articles: first (best) chunk of each article."""
    seen: dict[str, dict] = {}
    for h in hits:
        seen.setdefault(h["article"], {**h, "chunk_rank": h["rank"]})
    return [{**h, "rank": i} for i, h in enumerate(seen.values(), 1)]


def rank_of(hits: list[dict], article: str, key: str = "article") -> int | None:
    return next((h["rank"] for h in hits if h[key] == article), None)


def random_hit_at(n_articles: int, n_relevant: int, k: int) -> float:
    """Chance that k articles drawn at random contain at least one relevant one."""
    if n_articles <= 0 or k >= n_articles:
        return 1.0
    return 1 - math.comb(n_articles - n_relevant, k) / math.comb(n_articles, k)


# ---------------------------------------------------------------- report


def snippet(content: str) -> str:
    text = " ".join(content.split())
    return text[:SNIPPET] + ("…" if len(text) > SNIPPET else "")


def md_cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def write_report(out: Path, run: dict[str, Any]) -> str:
    labels = run["labels"]
    relevant = {label["chunk_id"] for label in labels}
    lines: list[str] = []
    add = lines.append
    add("# Generic contribution → agreement articles: one example\n")
    add(f"- Generic contribution: **{run['generic']['title']}**")
    add(f"- Agreement: **IDCC {run['idcc']}** ({run['corpus']['chunks']} chunks, "
        f"{run['corpus']['articles']} articles in `conventions`)")
    add(f"- Index `{run['provenance']['index']}`, built {run['provenance'].get('built_at')}, "
        f"KALI snapshot `{run['provenance']['kali_snapshot']}`, embedding model "
        f"`{run['provenance'].get('embedding_model_id')}`")
    add(f"- Run {run['run_at']}\n")
    add("## Labels: the articles the editors linked in the agreement contribution\n")
    add("| article id | number | editor's label | chunk title |")
    add("|---|---|---|---|")
    for label in labels:
        add(f"| `{label['chunk_id']}` | {label['num']} | {md_cell(label['label'] or '')} "
            f"| {md_cell(run['titles'].get(label['chunk_id'], ''))} |")
    if run["dropped"]:
        add("\nLeft out of the labels:\n")
        for reason, link in run["dropped"]:
            add(f"- {reason}: `{link['kali_id']}` {md_cell(link['label'] or '')}")
    ov = run["overlap"]
    add("\nThe queries use the generic contribution only; the agreement contribution is "
        "never read by the search. For information, "
        f"{ov['copied_from_generic']} of the {ov['agreement_chars']} characters of the "
        "agreement contribution are verbatim runs of the generic answer (it is written "
        "on top of it).\n")
    add("## Where the labelled articles rank\n")
    add("Article level (best chunk of each article), within the 64 chunks kept per list. "
        "`-` = not in the list.\n")
    header = "| article | " + " | ".join(f"{v} {m}" for v in VARIANTS for m in METHODS) + " |"
    add(header)
    add("|---|" + "---|" * (len(VARIANTS) * len(METHODS)))
    for label in labels:
        cells = []
        for v in VARIANTS:
            for m in METHODS:
                rank = rank_of(run["results"][v][m]["articles"], label["chunk_id"])
                cells.append(str(rank) if rank else "-")
        add(f"| {label['num']} `{label['chunk_id'][-8:]}` | " + " | ".join(cells) + " |")
    n_art, r = run["corpus"]["articles"], len(relevant)
    add(f"\nFor scale: among {n_art} articles with {r} relevant ones, a random top 10 "
        f"contains at least one of them with probability "
        f"{random_hit_at(n_art, r, 10):.1%} (top 20: {random_hit_at(n_art, r, 20):.1%}).\n")

    for v in VARIANTS:
        add(f"## Query `{v}`\n")
        text = run["queries"][v]
        add("```text")
        add(text if len(text) < 1200 else text[:1200] + f"\n… ({len(text)} chars)")
        add("```\n")
        for m in METHODS:
            add(f"### {v} / {m}: top {TOP} articles\n")
            add("| # | | article | score | start of the chunk |")
            add("|---|---|---|---|---|")
            for h in run["results"][v][m]["articles"][:TOP]:
                star = "★" if h["article"] in relevant else ""
                add(f"| {h['rank']} | {star} | {md_cell(h['title'])} `{h['article'][-8:]}` "
                    f"| {h['score']:.4f} | {md_cell(snippet(h['content']))} |")
            add("")
    text = "\n".join(lines) + "\n"
    (out / "report.md").write_text(text)
    return text


# ---------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--question", required=True, help="title prefix of the generic contribution")
    parser.add_argument("--idcc", required=True, help="agreement number, padded or not")
    args = parser.parse_args()

    settings = Settings()
    inputs = Inputs(
        store=make_store(settings, "local"),
        config=load_config(Path("config/local.toml")),
        settings=settings,
    )

    generic, agreement = pick_pair(settings, args.question, args.idcc)
    labels, dropped = build_labels(inputs, agreement)
    print(f"generic:   {generic.title}")
    print(f"agreement: IDCC {agreement.idcc}, contribution {agreement.cdtn_id}")
    print(f"labels ({len(labels)}):")
    for label in labels:
        print(f"  {label['chunk_id']}  {label['num']}  {label['label']}")
    for reason, link in dropped:
        print(f"  left out: {reason}: {link['kali_id']}")
    if not labels:
        sys.exit("no label for this pair")

    queries = build_queries(generic)
    check_no_label_in_queries(queries, labels)
    overlap = verbatim_overlap(generic, agreement)
    print(f"agreement text copied from the generic one: {overlap['copied_from_generic']} of "
          f"{overlap['agreement_chars']} chars")

    search = Search(settings)
    provenance = {
        **search.index_meta(),
        "kali_snapshot": inputs.manifest("kali").snapshot_id,
    }
    indexed = provenance["sources"]["conventions"]["snapshots"]["kali"]
    if indexed != provenance["kali_snapshot"]:
        sys.exit(f"index built from KALI {indexed}, labels from {provenance['kali_snapshot']}")

    vectors = embed_queries(settings, queries)
    chunks, articles = search.corpus(agreement.idcc)
    if not chunks:
        sys.exit(f"no conventions chunk for IDCC {agreement.idcc} (padding?)")

    results: dict[str, dict[str, dict]] = {}
    for variant in VARIANTS:
        knn = search.knn(vectors[variant], agreement.idcc)
        bm25 = search.bm25(queries[variant], agreement.idcc)
        hybrid = rrf(knn, bm25)
        # the fusion only reorders what the two lists hold
        assert {h["chunk"] for h in hybrid} <= {h["chunk"] for h in knn + bm25}
        results[variant] = {
            name: {"chunks": hits, "articles": collapse(hits)}
            for name, hits in (("knn", knn), ("bm25", bm25), ("hybrid", hybrid))
        }

    run = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "question": args.question,
        "idcc": norm_idcc(agreement.idcc),
        "generic": {"cdtn_id": generic.cdtn_id, "title": generic.title},
        "agreement": {"cdtn_id": agreement.cdtn_id, "title": agreement.title},
        "labels": labels,
        "dropped": dropped,
        "overlap": overlap,
        "queries": queries,
        "corpus": {"chunks": chunks, "articles": articles},
        "provenance": provenance,
        "titles": search.article_titles(agreement.idcc, [x["chunk_id"] for x in labels]),
        "results": results,
    }
    out = RUNS / f"generic-to-kali-example-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    (out / "results.json").write_text(json.dumps(run, ensure_ascii=False, indent=1, default=str))
    write_report(out, run)

    print(f"\nagreement corpus: {chunks} chunks, {articles} articles")
    print("rank of each labelled article (article level), '-' = not in the top 64 chunks")
    print(f"{'':28}" + "  ".join(f"{v[:4]}/{m:6}" for v in VARIANTS for m in METHODS))
    for label in labels:
        cells = []
        for v in VARIANTS:
            for m in METHODS:
                rank = rank_of(results[v][m]["articles"], label["chunk_id"])
                cells.append(f"{rank or '-':>11}")
        print(f"{label['num']:>6} {label['chunk_id'][-10:]:>12}   " + "  ".join(cells))
    print(f"\nreport: {out / 'report.md'}")


if __name__ == "__main__":
    main()
