import asyncio
import json

import httpx
import pytest
from conftest import ROOT
from openai import AsyncOpenAI
from test_judge import completion

from answer_eval.contexts import Context
from answer_eval.generate import (
    ANSWERS_FILE,
    CONTEXTS_FILE,
    RunConfigError,
    check_run_config,
    load_answers,
    run_generation,
)
from answer_eval.judging import answer_items
from answer_eval.prompt import Chunk, ChunkMetadata, WebPrompts
from answer_eval.report import build_report
from judge_eval.data import Criterion
from judge_eval.judge import ModelConfig
from judge_eval.runner import Prediction

PROMPTS = WebPrompts(ROOT / "generation/prompts/web-v2.0.json")


def context(query_id: str, idcc: str | None = None) -> Context:
    fiche = Chunk(
        content="Le préavis est d'un mois.",
        metadata=ChunkMetadata(id="d1", source="fiches_service_public", title="T"),
        grade=2,
    )
    return Context(
        query_id=query_id,
        text=f"Question {query_id} ?",
        idcc=idcc,
        idcc_name="CC" if idcc else None,
        fiches=[fiche],
        code=[],
        idcc_chunks=[],
    )


def model(name: str, **kwargs) -> ModelConfig:
    return ModelConfig(
        name=name,
        base_url="http://llm.test/v1",
        model=f"id-{name}",
        provider="p",
        params={"temperature": 0.3},
        **kwargs,
    )


def factory(handler):
    def make(config):
        return AsyncOpenAI(
            api_key="test",
            base_url=config.base_url,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )

    return make


def setup_run(tmp_path, contexts):
    (tmp_path / CONTEXTS_FILE).write_text(
        "".join(c.model_dump_json() + "\n" for c in contexts), encoding="utf-8"
    )


def test_generation_sends_the_web_prompt_and_resumes(tmp_path):
    contexts = [context("q1"), context("q2", idcc="1147")]
    setup_run(tmp_path, contexts)
    seen = []
    fail_once = {"q2"}

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        question = body["messages"][1]["content"]
        if body["model"] == "id-a" and "q2" in question and fail_once:
            fail_once.clear()
            return httpx.Response(500, text="boom")
        if body["model"] == "id-silent":
            return httpx.Response(200, json=completion(""))
        return httpx.Response(200, json=completion(f"Réponse à {question}"))

    generators = [model("a"), model("silent")]
    summary = asyncio.run(
        run_generation(generators, contexts, PROMPTS, tmp_path, factory(handler))
    )
    assert (summary.ok, summary.empty, summary.api_errors) == (1, 2, 1)

    body = next(b for b in seen if b["model"] == "id-a")
    assert body["temperature"] == 0.3
    system = body["messages"][0]["content"]
    assert system.startswith("# 🎯 Rôle")
    assert "Le préavis est d'un mois." in system
    q2_system = next(
        b["messages"][0]["content"] for b in seen if "q2" in b["messages"][1]["content"]
    )
    assert "(IDCC 1147)" in q2_system

    # Only the API error is retried
    seen.clear()
    summary = asyncio.run(
        run_generation(generators, contexts, PROMPTS, tmp_path, factory(handler))
    )
    assert (summary.attempted, summary.skipped, summary.ok) == (1, 3, 1)
    answers = {a.key: a for a in load_answers(tmp_path / ANSWERS_FILE)}
    assert answers[("a", "q2")].answer == "Réponse à Question q2 ?"
    assert answers[("a", "q2")].completion_tokens == 20
    assert answers[("silent", "q1")].status == "empty"

    items = answer_items(list(answers.values()), contexts)
    assert [i.id for i in items] == ["a::q1", "a::q2"]
    assert [i.question_id for i in items] == [0, 1]
    assert items[0].labels == {}


def test_run_config_refuses_changed_settings(tmp_path):
    setup_run(tmp_path, [context("q1")])
    check_run_config(tmp_path, PROMPTS, [model("a")])
    check_run_config(tmp_path, PROMPTS, [model("a"), model("b")])
    changed = model("a").model_copy(update={"params": {"temperature": 0}})
    with pytest.raises(RunConfigError, match="settings of 'a'"):
        check_run_config(tmp_path, PROMPTS, [changed])
    setup_run(tmp_path, [context("q2")])
    with pytest.raises(RunConfigError, match="contexts_sha256"):
        check_run_config(tmp_path, PROMPTS, [model("a")])


def test_report_counts_verdicts_and_refusals(tmp_path):
    from answer_eval.generate import Answer

    contexts = [context("q1"), context("q2")]
    answers = [
        Answer(
            generator="a",
            query_id="q1",
            status="ok",
            answer="Oui.",
            prompt_sha256="x",
            latency_s=2,
        ),
        Answer(
            generator="a",
            query_id="q2",
            status="ok",
            prompt_sha256="x",
            answer="Je ne dispose pas d'information sur ce point dans la base.",
        ),
        Answer(
            generator="b",
            query_id="q1",
            status="api_error",
            prompt_sha256="x",
            error="boom",
        ),
    ]
    predictions = [
        Prediction(
            status="ok",
            label=label,
            judge="j",
            prompt_version="v1",
            item_id=item,
            criterion=criterion,
        )
        for item, label in (("a::q1", True), ("a::q2", False))
        for criterion in Criterion
    ]
    summary, side_by_side, rows = build_report("r", contexts, answers, predictions)
    assert "| a | 2/2 | 0 | 0 | 0 | 1 | 0 | 2s |" in summary
    assert "| b | 0/2 | 0 | 1 |" in summary
    assert "| a | 50% (2) | 50% (2) | 50% (2) | 50% (2) |" in summary
    assert "### a (correct Oui, suffisant Oui, intelligible Oui)" in side_by_side
    assert "*api_error: boom*" in side_by_side
    assert {(r["generator"], r["query_id"], r["refusal"]) for r in rows} == {
        ("a", "q1", False),
        ("a", "q2", True),
        ("b", "q1", False),
    }
