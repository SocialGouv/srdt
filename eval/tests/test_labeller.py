import asyncio
import json
from pathlib import Path

import httpx
import pytest
from conftest import ROOT
from openai import AsyncOpenAI

from judge_eval.judge import ModelConfig, ParseError
from retrieval_eval.data import DocRecord, Query, load_qrels, text_sha256
from retrieval_eval.jsonl import read_jsonl
from retrieval_eval.labeller import (
    GradeLabeller,
    LabelFailure,
    LabelPromptBook,
    estimate_prompt_tokens,
    failures_path,
    label_pairs,
    pairs_to_label,
    parse_grade,
)

PROMPTS_ROOT = ROOT / "retrieval" / "prompts"


def completion(content: str) -> dict:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def query(qid: str = "q_1", idcc: str | None = None) -> Query:
    return Query(
        query_id=qid,
        text="Mon employeur peut-il refuser mon congé ?",
        source="prod",
        idcc=idcc,
        split="dev",
    )


def doc(doc_id: str = "d1", text: str = "Le congé est un droit.") -> DocRecord:
    return DocRecord(
        doc_id=doc_id,
        title=f"Fiche {doc_id}",
        url="https://x",
        source="fiches_service_public",
        text=text,
        text_sha256=text_sha256(text),
    )


def make_labeller(handler, max_chars: int = 12000) -> GradeLabeller:
    client = AsyncOpenAI(
        api_key="test",
        base_url="http://llm.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    config = ModelConfig(name="m", base_url="http://llm.test/v1", model="model-x")
    prompts = LabelPromptBook(PROMPTS_ROOT, "v1", max_chars=max_chars)
    return GradeLabeller(config, prompts, client=client)


def answer(grade_json: str):
    def handler(request):
        return httpx.Response(200, json=completion(grade_json))

    return handler


def run(coro):
    return asyncio.run(coro)


# --- parser ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text, grade",
    [
        ('{"reasoning": "ok", "grade": 2}', 2),
        ('{"grade": "1", "reasoning": "x"}', 1),
        ('{"grade": 0.0}', 0),
        ('```json\n{"reasoning": "r", "grade": 1}\n```', 1),
        ('<think>{"grade": 0}</think>{"reasoning": "r", "grade": 2}', 2),
        ('Voici : {"reasoning": "r", "grade": 1} merci', 1),
        ('{"reasoning": "coupé", "grade": 2', 2),  # truncated after the grade
    ],
)
def test_parse_grade_accepts(text, grade):
    assert parse_grade(text).grade == grade


@pytest.mark.parametrize(
    "text",
    [
        "",
        "La note est 2.",  # never guessed from prose
        '{"reasoning": "r"}',
        '{"grade": 3}',
        '{"grade": true}',
        '{"grade": "deux"}',
        '{"grade": -1}',
    ],
)
def test_parse_grade_rejects(text):
    with pytest.raises(ParseError):
        parse_grade(text)


# --- prompts --------------------------------------------------------------


def test_prompt_contains_guideline_question_document_and_no_comments():
    prompts = LabelPromptBook(PROMPTS_ROOT, "v1")
    messages, truncated = prompts.render(query(idcc="1979"), doc())
    system, user = messages[0]["content"], messages[1]["content"]

    assert not truncated
    assert "répond directement" in system  # the guideline is part of the system prompt
    assert "DRAFT" not in system and "<!--" not in system
    assert "Mon employeur peut-il refuser mon congé ?" in user
    assert "IDCC) : 1979" in user
    assert "Le congé est un droit." in user and "Fiche d1" in user


def test_no_idcc_line_without_idcc():
    messages, _ = LabelPromptBook(PROMPTS_ROOT, "v1").render(query(), doc())
    assert "IDCC" not in messages[1]["content"]


def test_long_documents_are_cut_and_flagged():
    prompts = LabelPromptBook(PROMPTS_ROOT, "v1", max_chars=50)
    messages, truncated = prompts.render(query(), doc(text="a" * 500))
    assert truncated
    assert "a" * 50 in messages[1]["content"]
    assert "a" * 51 not in messages[1]["content"]
    assert "tronqué" in messages[1]["content"]


def test_prompt_hash_depends_on_max_chars():
    a = LabelPromptBook(PROMPTS_ROOT, "v1", max_chars=100).sha256
    b = LabelPromptBook(PROMPTS_ROOT, "v1", max_chars=200).sha256
    assert a != b


# --- labeller -------------------------------------------------------------


def test_grade_sends_the_grade_schema_and_returns_the_grade():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json=completion('{"reasoning": "direct", "grade": 2}')
        )

    grading, truncated = run(make_labeller(handler).grade(query(), doc()))

    assert grading.status == "ok" and grading.grade == 2 and not truncated
    assert grading.reasoning == "direct"
    assert (grading.prompt_tokens, grading.completion_tokens) == (100, 20)
    schema = seen[0]["response_format"]["json_schema"]
    assert schema["name"] == "grade"
    assert schema["schema"]["properties"]["grade"]["enum"] == [0, 1, 2]


def test_unusable_reply_is_a_parse_error_and_http_failure_an_api_error():
    grading, _ = run(make_labeller(answer("pas de JSON")).grade(query(), doc()))
    assert grading.status == "parse_error" and grading.grade is None

    def boom(request):
        return httpx.Response(500, text="down")

    grading, _ = run(make_labeller(boom).grade(query(), doc()))
    assert grading.status == "api_error" and grading.grade is None


def test_json_schema_rejection_steps_down_the_fallback_chain():
    modes = []

    def handler(request):
        body = json.loads(request.content)
        modes.append(body.get("response_format", {}).get("type"))
        if modes[-1] == "json_schema":
            return httpx.Response(400, json={"error": {"message": "unsupported"}})
        return httpx.Response(200, json=completion('{"reasoning": "r", "grade": 1}'))

    grading, _ = run(make_labeller(handler).grade(query(), doc()))
    assert grading.grade == 1 and grading.response_mode == "json_object"
    assert modes == ["json_schema", "json_object"]


# --- running over pairs ---------------------------------------------------


def test_label_pairs_stores_qrels_and_resumes(tmp_path: Path):
    path = tmp_path / "qrels.jsonl"
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=completion('{"reasoning": "r", "grade": 1}'))

    labeller = make_labeller(handler)
    pairs = [(query(), doc("d1")), (query(), doc("d2")), (query("q_2"), doc("d1"))]

    first = run(label_pairs(labeller, pairs, path))
    assert first.labelled == 3 and first.skipped == 0
    qrels = load_qrels(path)
    assert {(q.query_id, q.doc_id, q.grade) for q in qrels} == {
        ("q_1", "d1", 1),
        ("q_1", "d2", 1),
        ("q_2", "d1", 1),
    }
    assert all(q.labeller == "llm:m" and q.prompt_version == "v1" for q in qrels)
    assert all(q.text_sha256 for q in qrels)

    again = run(label_pairs(labeller, pairs, path))
    assert again.attempted == 0 and again.skipped == 3
    assert len(calls) == 3


def test_a_changed_document_text_is_labelled_again(tmp_path: Path):
    path = tmp_path / "qrels.jsonl"
    labeller = make_labeller(answer('{"reasoning": "r", "grade": 2}'))
    run(label_pairs(labeller, [(query(), doc("d1", "ancien texte"))], path))
    summary = run(label_pairs(labeller, [(query(), doc("d1", "nouveau texte"))], path))
    assert summary.labelled == 1 and summary.skipped == 0


def test_parse_errors_are_final_api_errors_are_retried(tmp_path: Path):
    path = tmp_path / "qrels.jsonl"
    pairs = [(query(), doc("d1"))]

    bad = make_labeller(answer("pas de JSON"))
    assert run(label_pairs(bad, pairs, path)).parse_errors == 1
    assert run(label_pairs(bad, pairs, path)).skipped == 1  # not paid for twice
    (failure,) = read_jsonl(failures_path(path), LabelFailure)
    assert failure.status == "parse_error" and failure.raw == "pas de JSON"

    other = tmp_path / "other.jsonl"

    def boom(request):
        return httpx.Response(500, text="down")

    down = make_labeller(boom)
    assert run(label_pairs(down, pairs, other)).api_errors == 1
    assert run(label_pairs(down, pairs, other)).attempted == 1  # retried
    assert load_qrels(other) == []


def test_other_labellers_and_prompt_versions_do_not_count_as_done(tmp_path: Path):
    path = tmp_path / "qrels.jsonl"
    pairs = [(query(), doc("d1"))]
    run(label_pairs(make_labeller(answer('{"grade": 1}')), pairs, path))

    other = make_labeller(answer('{"grade": 2}'))
    other.labeller = "llm:other"
    assert run(label_pairs(other, pairs, path)).labelled == 1


def test_pairs_to_label_and_token_estimate():
    pool = {"q_1": {"d1": ["knn@1"], "d2": ["knn@2"]}, "q_2": {"d1": ["knn@1"]}}
    docs = {"d1": doc("d1")}
    pairs, missing = pairs_to_label([query("q_1"), query("q_2")], pool, docs)

    assert [(q.query_id, d.doc_id) for q, d in pairs] == [("q_1", "d1"), ("q_2", "d1")]
    assert missing == [("q_1", "d2")]
    prompts = LabelPromptBook(PROMPTS_ROOT, "v1")
    assert estimate_prompt_tokens(prompts, pairs) > 2 * 100  # guideline alone is long
