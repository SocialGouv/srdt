import asyncio

import httpx
import pytest
from fake_api import chunk, make_api

from answer_eval.contexts import build_contexts, idcc_title, select_fiches
from retrieval_eval.data import DocRecord, Qrel, Query, text_sha256


def doc(doc_id: str) -> DocRecord:
    text = f"texte {doc_id}"
    return DocRecord(
        doc_id=doc_id,
        title=f"Titre {doc_id}",
        url=f"https://example.org/{doc_id}",
        source="fiches_service_public",
        text=text,
        text_sha256=text_sha256(text),
    )


def qrel(doc_id: str, grade: int, query_id: str = "q1") -> Qrel:
    return Qrel(
        query_id=query_id,
        doc_id=doc_id,
        grade=grade,
        labeller="llm:m",
        text_sha256=text_sha256(f"texte {doc_id}"),
    )


DOCS = {d: doc(d) for d in "abcdefg"}


def test_fiches_best_grade_first_then_production_rank_and_capped():
    qrels = [
        qrel("a", 1),
        qrel("b", 2),
        qrel("c", 0),
        qrel("d", 1),
        qrel("e", 2),
        qrel("f", 1),
        qrel("g", 2, query_id="q2"),
    ]
    ranks = {("q1", "a"): 5, ("q1", "d"): 1, ("q1", "b"): 9, ("q1", "e"): 3}
    fiches = select_fiches("q1", qrels, DOCS, ranks, min_grade=1, max_fiches=4)
    # grade 2 by rank (e, b), then grade 1 by rank (d, a); f (no rank) is cut
    assert [f.metadata.id for f in fiches] == ["e", "b", "d", "a"]
    assert [f.grade for f in fiches] == [2, 2, 1, 1]
    assert fiches[0].content == "texte e"
    assert fiches[0].metadata.source == "fiches_service_public"

    only_best = select_fiches("q1", qrels, DOCS, ranks, min_grade=2, max_fiches=10)
    assert [f.metadata.id for f in only_best] == ["e", "b"]


def test_label_on_another_text_is_refused():
    stale = qrel("a", 2).model_copy(update={"text_sha256": "other"})
    with pytest.raises(ValueError, match="another text"):
        select_fiches("q1", [stale], DOCS, {}, min_grade=1, max_fiches=10)


def lookup_client(titles: dict[str, str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        hits = [
            {"_source": {"num": int(num), "title": title}}
            for num, title in titles.items()
            if int(num) == int(q)
        ]
        return httpx.Response(200, json={"hits": {"hits": hits}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_idcc_title_matches_the_number():
    async def go():
        async with lookup_client({"953": "Charcuterie"}) as client:
            return await idcc_title(client, "0953")

    assert asyncio.run(go()) == "Charcuterie"


def test_build_contexts_runs_the_web_searches():
    code_chunks = [chunk(f"art{i}", 1 - i / 10) for i in range(7)]
    for c in code_chunks:
        c["metadata"]["source"] = "code_du_travail"
    fake, api = make_api(
        search_results={True: code_chunks},
        rerank_scores={f"art{i}": i for i in range(7)} | {"cc1": 1, "cc2": 2},
        idcc_chunks=[chunk("cc1", 0.9), chunk("cc2", 0.8)],
    )
    queries = [
        Query(query_id="q1", text="Q1 ?", source="idcc22", idcc="1147", split="dev"),
        Query(query_id="q2", text="Q2 ?", source="idcc22", split="dev"),
        Query(query_id="q3", text="Q3 ?", source="idcc22", split="dev"),
    ]
    qrels = [qrel("a", 2), qrel("b", 1), qrel("c", 1, query_id="q2")]

    async def go():
        async with lookup_client({"1147": "Cabinets médicaux"}) as lookup:
            return await build_contexts(queries, qrels, DOCS, {}, api, lookup)

    contexts = asyncio.run(go())
    q1, q2, q3 = contexts

    searches = fake.routes("/search")
    assert len(searches) == 2  # q3 has no fiche: no article search
    first = next(s for s in searches if s["prompts"] == ["Q1 ?"])
    assert first["options"] == {
        "top_K": 64,
        "hybrid": True,
        "collections": ["code_du_travail"],
        "linked_from": ["a", "b"],
    }
    # best five reranked articles, rerank score kept
    assert [c.metadata.id for c in q1.code] == [f"art{i}" for i in (6, 5, 4, 3, 2)]
    assert q1.code[0].rerank_score == 6

    (idcc_call,) = fake.routes("/idcc/search")
    assert idcc_call["idcc"] == "1147"
    assert idcc_call["options"]["collections"] == ["conventions"]
    assert [c.metadata.id for c in q1.idcc_chunks] == ["cc2", "cc1"]
    assert q1.idcc_name == "Cabinets médicaux"

    assert q2.idcc is None and q2.idcc_chunks == [] and q2.idcc_name is None
    assert [f.metadata.id for f in q2.fiches] == ["c"]
    assert q3.fiches == [] and q3.code == []
