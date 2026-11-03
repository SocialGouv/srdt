import asyncio
import json
import re

import httpx
from fake_api import chunk, make_api
from openai import AsyncOpenAI
from test_judge import completion

from answer_eval.contexts import COPIED_FIELDS, Context, add_jurisprudence
from answer_eval.jurisprudence import (
    JurisprudenceFilter,
    parse_verdict,
    search_jurisprudence,
)
from answer_eval.prompt import Chunk, ChunkMetadata
from judge_eval.judge import ModelConfig

CONFIG = ModelConfig(
    name="prod/mistral-large-latest",
    base_url="http://llm.test/v1",
    model="mistral-large-latest",
    provider="mistral",
    params={"temperature": 0.3},
)


def make_filter(reply, seen=None) -> JurisprudenceFilter:
    """`reply(decision_id)` gives the model's text, or an int HTTP status to fail."""

    def handler(request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        decision = re.search(r"decision/(\w+)", body["messages"][1]["content"])
        out = reply(decision.group(1) if decision else None)
        if isinstance(out, int):
            return httpx.Response(out, text="boom")
        return httpx.Response(200, json=completion(out))

    client = AsyncOpenAI(
        api_key="test",
        base_url=CONFIG.base_url,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    return JurisprudenceFilter(client, CONFIG, "INSTRUCTION")


def decision(decision_id: str, score: float = 0.5) -> dict:
    c = chunk(f"{decision_id}-0", score, content=f"SOMMAIRE {decision_id}")
    c["metadata"] |= {
        "source": "judilibre",
        "url": f"https://www.courdecassation.fr/decision/{decision_id}",
        "number": "17-28.767",
        "decision_date": "2019-05-09",
    }
    return c


def as_chunk(c: dict) -> Chunk:
    return Chunk.model_validate(c)


def test_parse_verdict_like_the_web():
    assert parse_verdict("OUI") is True
    assert parse_verdict("  **non**.") is False
    assert parse_verdict("Oui, car") is True
    assert parse_verdict("NONE") is None  # word boundary
    assert parse_verdict("Je pense que OUI") is None


def test_search_keeps_the_five_best_reranked_decisions():
    decisions = [decision(f"d{i}", 1 - i / 10) for i in range(8)]
    fake, api = make_api(
        collection_results={"judilibre": decisions},
        rerank_scores={f"d{i}-0": i for i in range(8)},
    )
    found = asyncio.run(search_jurisprudence(api, "Q ?"))
    (call,) = fake.routes("/search")
    assert call["options"] == {
        "top_K": 64,
        "hybrid": True,
        "collections": ["judilibre"],
    }
    assert [c.metadata.id for c in found] == [f"d{i}-0" for i in (7, 6, 5, 4, 3)]
    assert found[0].rerank_score == 7
    assert found[0].metadata.model_extra["number"] == "17-28.767"


def test_search_falls_back_to_search_order_without_rerank():
    decisions = [decision(f"d{i}") for i in range(7)]
    fake, api = make_api(collection_results={"judilibre": decisions})
    original = fake.handler

    def handler(request):
        if request.url.path.endswith("/rerank"):
            return httpx.Response(200, json={"time": 0, "results": []})
        return original(request)

    fake.handler = handler
    api = fake.api()
    found = asyncio.run(search_jurisprudence(api, "Q ?"))
    assert [c.metadata.id for c in found] == [f"d{i}-0" for i in range(5)]


def test_filter_keeps_oui_drops_non_and_unparsable_keeps_on_errors():
    replies = {"ok": "OUI", "no": "NON", "bad": "Peut-être", "down": 500}
    calls: dict[str, int] = {}

    def reply(decision_id):
        calls[decision_id] = calls.get(decision_id, 0) + 1
        if decision_id == "flaky" and calls["flaky"] == 1:
            return 503
        return replies.get(decision_id, "OUI")

    seen = []
    decisions = make_filter(reply, seen)
    chunks = [as_chunk(decision(d)) for d in ("ok", "no", "bad", "down", "flaky")]
    result = asyncio.run(decisions.filter("Ma question ?", chunks))

    by_id = {r.chunk.metadata.id.removesuffix("-0"): r for r in result}
    assert [r.chunk.metadata.id for r in result] == [c.metadata.id for c in chunks]
    assert by_id["ok"].kept and by_id["ok"].verdict is True
    assert not by_id["no"].kept and by_id["no"].verdict is False
    assert not by_id["bad"].kept and by_id["bad"].raw == "Peut-être"
    assert by_id["down"].kept and by_id["down"].verdict is None
    assert "InternalServerError" in by_id["down"].error
    assert calls["down"] == 2  # retried once
    assert by_id["flaky"].kept and by_id["flaky"].error is None and calls["flaky"] == 2

    body = seen[0]
    assert body["model"] == "mistral-large-latest" and body["temperature"] == 0.3
    assert body["messages"][0] == {"role": "system", "content": "INSTRUCTION"}
    user = body["messages"][1]["content"]
    assert user.startswith("Question : Ma question ?\n\nArrêt :\nSource: judilibre (")
    assert "Titre: Arrêt numéro 17-28.767 du 09/05/2019\n" in user
    assert user.endswith("---\n\nRépondez uniquement par OUI ou NON.")


def source_context(query_id: str) -> Context:
    fiche = Chunk(
        content="Texte",
        metadata=ChunkMetadata(id="f1", source="fiches_service_public", url="u"),
        grade=2,
    )
    code = Chunk.model_validate(
        {
            "content": "Article",
            "metadata": {"id": "c1", "source": "code_du_travail", "extra": [1, 2]},
            "rerank_score": 0.123456789,
        }
    )
    return Context(
        query_id=query_id,
        text=f"Question {query_id} ?",
        idcc="0029",
        idcc_name="CC",
        fiches=[fiche],
        code=[code],
        idcc_chunks=[],
    )


def test_add_jurisprudence_copies_everything_else_and_searches_only_judilibre():
    lines = [source_context(q).model_dump_json() for q in ("q1", "q2")]
    fake, api = make_api(
        collection_results={"judilibre": [decision("d1"), decision("d2")]},
        rerank_scores={"d1-0": 1, "d2-0": 2},
    )
    decisions = make_filter(lambda d: "OUI" if d == "d1" else "NON")
    contexts = asyncio.run(add_jurisprudence(lines, api, decisions))

    for line, context in zip(lines, contexts, strict=True):
        source = json.loads(line)
        new = context.model_dump(mode="json")
        assert {f: new[f] for f in COPIED_FIELDS} == {
            f: source[f] for f in COPIED_FIELDS
        }
        assert [c.metadata.id for c in context.jurisprudence] == ["d1-0"]
        assert [c.kept for c in context.jurisprudence_candidates] == [False, True]

    assert fake.routes("/idcc/search") == []
    assert {tuple(s["options"]["collections"]) for s in fake.routes("/search")} == {
        ("judilibre",)
    }
