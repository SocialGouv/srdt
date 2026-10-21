import asyncio
import json
from pathlib import Path

import httpx
import pytest
from conftest import ROOT, make_item
from openai import AsyncOpenAI

from judge_eval.data import Criterion
from judge_eval.judge import (
    ModelConfig,
    OpenAICompatibleJudge,
    describe_error,
    load_models,
)
from judge_eval.prompts import PromptBook

PROMPTS = PromptBook(ROOT / "prompts", "v1")


def completion(content, finish_reason="stop"):
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def make_judge(handler, **config) -> OpenAICompatibleJudge:
    client = AsyncOpenAI(
        api_key="test",
        base_url="http://llm.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    cfg = ModelConfig(
        name="m", base_url="http://llm.test/v1", model="model-x", **config
    )
    return OpenAICompatibleJudge(cfg, PROMPTS, client=client)


def run(judge, item=None, criterion=Criterion.SUFFISANT):
    return asyncio.run(judge.judge(item or make_item(), criterion))


def test_successful_call_sends_question_answer_and_params():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, json=completion('{"reasoning": "complet", "verdict": "Oui"}')
        )

    verdict = run(make_judge(handler), make_item(answer="Réponse spécifique."))

    assert verdict.status == "ok" and verdict.label is True
    assert verdict.reasoning == "complet"
    assert (verdict.prompt_tokens, verdict.completion_tokens) == (100, 20)
    assert verdict.response_mode == "json_schema"
    assert verdict.served_model == "m"  # model id reported by the server
    body = seen[0]
    assert body["model"] == "model-x" and body["temperature"] == 0
    assert body["response_format"]["type"] == "json_schema"
    assert "Question ?" in body["messages"][1]["content"]
    assert "Réponse spécifique." in body["messages"][1]["content"]
    assert "suffisante" in body["messages"][0]["content"]  # the criterion definition


def test_empty_params_table_sends_no_temperature():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=completion('{"verdict": "Non"}'))

    run(make_judge(handler, params={}))
    assert "temperature" not in seen[0]


def test_falls_back_when_response_format_is_rejected_and_remembers_it():
    formats = []

    def handler(request):
        body = json.loads(request.content)
        fmt = body.get("response_format", {}).get("type")
        formats.append(fmt)
        if fmt == "json_schema":
            return httpx.Response(400, json={"error": {"message": "unsupported"}})
        return httpx.Response(200, json=completion('{"verdict": "Non"}'))

    judge = make_judge(handler)
    first, second = run(judge), run(judge)

    assert formats == ["json_schema", "json_object", "json_object"]
    assert first.response_mode == second.response_mode == "json_object"
    assert first.label is False


def test_last_resort_is_prompt_only():
    formats = []

    def handler(request):
        fmt = json.loads(request.content).get("response_format", {}).get("type")
        formats.append(fmt)
        if fmt is not None:
            return httpx.Response(422, json={"error": {"message": "nope"}})
        return httpx.Response(200, json=completion('{"verdict": "Oui"}'))

    verdict = run(make_judge(handler))
    assert formats == ["json_schema", "json_object", None]
    assert verdict.response_mode == "prompt" and verdict.label is True


def test_unrelated_400_does_not_downgrade_the_mode():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content).get("response_format", {}).get("type"))
        return httpx.Response(400, json={"error": {"message": "context too long"}})

    judge = make_judge(handler)
    verdict = run(judge)
    assert verdict.status == "api_error" and "BadRequestError" in verdict.error
    assert judge._mode_index == 0  # nothing proved the mode was the problem


def test_pinned_response_format_does_not_fall_back():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "unsupported"}})

    verdict = run(make_judge(handler, response_format="json_schema"))
    assert verdict.status == "api_error" and len(calls) == 1


def test_server_error_is_an_api_error_not_a_crash():
    verdict = run(
        make_judge(lambda r: httpx.Response(500, json={"error": {"message": "boom"}}))
    )
    assert verdict.status == "api_error" and verdict.label is None


def test_unparsable_reply_is_a_parse_error_with_raw_text_kept():
    verdict = run(
        make_judge(
            lambda r: httpx.Response(200, json=completion("Je ne sais pas.", "length"))
        )
    )
    assert verdict.status == "parse_error" and verdict.label is None
    assert verdict.raw == "Je ne sais pas." and verdict.finish_reason == "length"


def test_missing_api_key_variable_fails_early(monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    cfg = ModelConfig(
        name="m", base_url="http://x/v1", model="x", api_key_env="SOME_KEY"
    )
    with pytest.raises(RuntimeError, match="SOME_KEY"):
        OpenAICompatibleJudge(cfg, PROMPTS)


def write_models(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "models.toml"
    path.write_text(text)
    return path


PROVIDERS = """
[providers.a]
base_url = "http://a/v1"
api_key_env = "A_KEY"
concurrency = 3
timeout_s = 30

[providers.b]
base_url = "http://b/v1"
response_format = "json_object"
params = {}
"""


def test_several_models_share_their_provider_settings(tmp_path: Path):
    path = write_models(
        tmp_path,
        PROVIDERS
        + """
[[models]]
provider = "a"
model = "m1"

[[models]]
provider = "a"
model = "m2"
name = "short"
max_retries = 1

[[models]]
provider = "b"
model = "org/m3"
""",
    )
    m1, m2, m3 = load_models(path)

    assert [m.name for m in (m1, m2, m3)] == ["a/m1", "short", "b/org/m3"]
    assert (m1.base_url, m1.api_key_env, m1.concurrency, m1.timeout_s) == (
        "http://a/v1", "A_KEY", 3, 30,
    )  # fmt: skip
    assert m1.params == {"temperature": 0}  # default when the provider sets none
    assert m1.max_retries == 5 and m2.max_retries == 1  # per-model override
    assert m2.base_url == "http://a/v1" and m2.model == "m2"
    # provider-level settings flow down, including an explicit empty params table
    assert m3.response_format == "json_object" and m3.params == {}
    assert m3.api_key_env is None
    assert m1.provider == "a" and m3.provider == "b"


def test_model_override_wins_over_provider(tmp_path: Path):
    path = write_models(
        tmp_path,
        PROVIDERS
        + """
[[models]]
provider = "b"
model = "m"
response_format = "prompt"
params = { temperature = 0.2 }
""",
    )
    (config,) = load_models(path)
    assert config.response_format == "prompt"
    assert config.params == {"temperature": 0.2}


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ('[[models]]\nprovider = "zzz"\nmodel = "m"\n', "unknown provider 'zzz'"),
        (
            '[[models]]\nprovider = "a"\nmodel = "m"\n'
            '[[models]]\nprovider = "a"\nmodel = "m"\n',
            "duplicated",
        ),
        ('[[models]]\nprovider = "a"\nmodel = "m"\nname = "baseline:x"\n', "reserved"),
        # old flat format: endpoint settings no longer belong in a model entry
        (
            '[[models]]\nprovider = "a"\nmodel = "m"\nbase_url = "http://x/v1"\n',
            "entry 1",
        ),
    ],
)
def test_invalid_models_files_are_rejected(tmp_path: Path, entries, message):
    with pytest.raises(ValueError, match=message):
        load_models(write_models(tmp_path, PROVIDERS + entries))


def test_models_file_is_valid():
    models = load_models(ROOT / "config" / "models.toml")
    assert {m.provider for m in models} >= {"albert", "mistral", "scaleway"}
    assert all(m.base_url.endswith("/v1") for m in models)
    assert all(m.api_key_env for m in models)  # keys come from the environment
    assert len({m.name for m in models}) == len(models)


# --- error messages -------------------------------------------------------


def unreachable(cause: BaseException | None = None):
    """A handler whose connection fails, as the SDK sees a network error."""

    def handler(request):
        error = httpx.ConnectError("connect failed")
        if cause is not None:
            raise error from cause
        raise error

    return handler


def test_connection_error_message_includes_the_underlying_cause():
    cause = ConnectionResetError(54, "Connection reset by peer")
    verdict = run(make_judge(unreachable(cause)))

    assert verdict.status == "api_error"
    assert verdict.error == (
        "APIConnectionError: Connection error. "
        "(cause: ConnectionResetError: [Errno 54] Connection reset by peer)"
    )


def test_connection_error_without_a_deeper_cause_shows_the_httpx_error():
    verdict = run(make_judge(unreachable()))
    assert "APIConnectionError: Connection error." in verdict.error
    assert "(cause: ConnectError: connect failed)" in verdict.error


def test_http_status_errors_get_no_redundant_cause():
    verdict = run(
        make_judge(lambda r: httpx.Response(500, json={"error": {"message": "boom"}}))
    )
    assert verdict.error.startswith("InternalServerError: ")
    assert "cause" not in verdict.error


def test_describe_error_follows_the_chain_to_the_root_and_survives_cycles():
    root = OSError(8, "nodename nor servname provided")
    middle = RuntimeError("middle")
    middle.__cause__ = root
    top = ValueError("top")
    top.__cause__ = middle
    assert describe_error(top) == (
        "ValueError: top (cause: OSError: [Errno 8] nodename nor servname provided)"
    )

    a, b = ValueError("a"), ValueError("b")
    a.__cause__, b.__cause__ = b, a  # pathological cycle
    assert describe_error(a).startswith("ValueError: a (cause: ValueError: ")

    assert describe_error(TimeoutError()) == "TimeoutError"  # empty message
