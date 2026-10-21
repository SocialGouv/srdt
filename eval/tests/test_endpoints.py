import asyncio
import json

import httpx
from conftest import ROOT, make_item
from openai import AsyncOpenAI

from judge_eval.data import Criterion
from judge_eval.endpoints import check_models, list_model_ids, probe_models
from judge_eval.judge import ModelConfig
from judge_eval.prompts import PromptBook


def client_for(handler) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key="test",
        base_url="http://llm.test/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


def models_response(*entries):
    return httpx.Response(200, json={"object": "list", "data": list(entries)})


def entry(model_id, **extra):
    return {"id": model_id, "object": "model", "created": 0, "owned_by": "x", **extra}


def config(model: str, name: str = "m", base_url: str = "http://llm.test/v1"):
    return ModelConfig(name=name, base_url=base_url, model=model)


def test_lists_ids_and_aliases():
    client = client_for(
        lambda r: models_response(
            entry("mistral-large-2411", aliases=["mistral-large-latest"]),
            entry("open-mistral-nemo"),
        )
    )
    ids = asyncio.run(list_model_ids(client))
    assert ids == {"mistral-large-2411", "mistral-large-latest", "open-mistral-nemo"}


def test_check_reports_served_missing_and_unlistable_models():
    def handler(request):
        if request.headers["Authorization"] == "Bearer denied":
            return httpx.Response(403, json={"error": {"message": "forbidden"}})
        return models_response(entry("good-model"))

    def client(key):
        return AsyncOpenAI(
            api_key=key,
            base_url="http://llm.test/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )

    configs = [
        config("good-model", "ok", base_url="http://ok/v1"),
        config("god-model", "typo", base_url="http://typo/v1"),
        config("x", "nolist", base_url="http://nolist/v1"),
    ]
    keys = {"ok": "k", "typo": "k", "nolist": "denied"}
    checks = asyncio.run(
        check_models(configs, client_factory=lambda c: client(keys[c.name]))
    )

    ok, typo, nolist = checks
    assert ok.listed is True
    assert typo.listed is False and typo.available == {"good-model"}
    assert nolist.listed is None and "PermissionDeniedError" in nolist.error


def test_an_endpoint_shared_by_several_models_is_listed_once():
    requests = []

    def handler(request):
        requests.append(request.url)
        return models_response(entry("m1"), entry("m2"))

    configs = [
        config("m1", "a/m1", base_url="http://a/v1"),
        config("m2", "a/m2", base_url="http://a/v1"),
        config("typo", "a/typo", base_url="http://a/v1"),
        config("m1", "b/m1", base_url="http://b/v1"),
    ]
    checks = asyncio.run(
        check_models(configs, client_factory=lambda c: client_for(handler))
    )

    assert len(requests) == 2  # one listing per endpoint, not per model
    assert [c.listed for c in checks] == [True, True, False, True]


def chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "served-id",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def test_probe_reports_each_model_and_one_failure_does_not_stop_the_others():
    chat_calls = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return models_response(*(entry(m) for m in ("good", "garbled", "broken")))
        model = json.loads(request.content)["model"]
        chat_calls.append(model)
        if model == "broken":
            return httpx.Response(500, json={"error": {"message": "boom"}})
        if model == "garbled":
            return chat_response("no json here")
        return chat_response('{"reasoning": "ok", "verdict": "Oui"}')

    def client_factory(config):
        if config.name == "nokey":
            raise RuntimeError("Environment variable KEYVAR is not set")
        return client_for(handler)

    configs = [
        config("good", "good"),
        config("typo", "typo"),
        config("x", "nokey"),
        config("garbled", "garbled"),
        config("broken", "broken"),
    ]
    probes = asyncio.run(
        probe_models(
            configs,
            make_item(),
            Criterion.CORRECT_EN_DROIT,
            PromptBook(ROOT / "prompts", "v1"),
            client_factory=client_factory,
        )
    )

    assert [p.config.name for p in probes] == [c.name for c in configs]  # same order
    good, typo, nokey, garbled, broken = probes
    assert good.ok and good.verdict.label is True
    assert good.verdict.served_model == "served-id"
    assert typo.verdict is None and "not served" in typo.skipped
    assert nokey.verdict is None and "KEYVAR" in nokey.skipped
    assert garbled.verdict.status == "parse_error" and not garbled.ok
    assert broken.verdict.status == "api_error" and not broken.ok
    # Only models that could be called were called, once each.
    assert sorted(chat_calls) == ["broken", "garbled", "good"]


def test_probe_still_calls_a_model_whose_endpoint_cannot_be_listed():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(403, json={"error": {"message": "forbidden"}})
        return chat_response('{"reasoning": "ok", "verdict": "Non"}')

    probes = asyncio.run(
        probe_models(
            [config("m")],
            make_item(),
            Criterion.SUFFISANT,
            PromptBook(ROOT / "prompts", "v1"),
            client_factory=lambda c: client_for(handler),
        )
    )
    assert probes[0].ok and probes[0].verdict.label is False


def test_listing_failure_message_includes_the_underlying_cause():
    def handler(request):
        raise httpx.ConnectError("connect failed") from OSError(
            8, "nodename nor servname provided, or not known"
        )

    (check,) = asyncio.run(
        check_models([config("m")], client_factory=lambda c: client_for(handler))
    )
    assert check.listed is None
    assert "APIConnectionError: Connection error." in check.error
    assert "OSError: [Errno 8] nodename nor servname provided" in check.error


# --- client lifecycle -----------------------------------------------------
# Clients left open when their event loop ends fail noisily ("Event loop is
# closed") when garbage-collected inside a later loop, e.g. the one of `run`.


class ClientRecorder:
    """Client factory that remembers what it created."""

    def __init__(self, handler):
        self.handler = handler
        self.created: list[AsyncOpenAI] = []

    def __call__(self, config):
        client = client_for(self.handler)
        self.created.append(client)
        return client


def test_check_models_closes_the_clients_it_creates():
    factory = ClientRecorder(lambda r: models_response(entry("m")))
    asyncio.run(check_models([config("m")], client_factory=factory))
    assert len(factory.created) == 1 and factory.created[0].is_closed()


def test_check_models_closes_its_clients_even_when_listing_fails():
    factory = ClientRecorder(
        lambda r: httpx.Response(403, json={"error": {"message": "no"}})
    )
    (check,) = asyncio.run(check_models([config("m")], client_factory=factory))
    assert check.listed is None and factory.created[0].is_closed()


def test_check_models_leaves_caller_owned_clients_open():
    factory = ClientRecorder(lambda r: models_response(entry("m")))
    asyncio.run(
        check_models([config("m")], client_factory=factory, close_clients=False)
    )
    assert not factory.created[0].is_closed()


def test_probe_models_closes_every_client_it_created():
    def handler(request):
        if request.url.path.endswith("/models"):
            return models_response(entry("a"), entry("b"))
        return chat_response('{"reasoning": "ok", "verdict": "Oui"}')

    factory = ClientRecorder(handler)
    probes = asyncio.run(
        probe_models(
            [config("a", "a"), config("b", "b"), config("typo", "typo")],
            make_item(),
            Criterion.SUFFISANT,
            PromptBook(ROOT / "prompts", "v1"),
            client_factory=factory,
        )
    )
    assert [p.ok for p in probes] == [True, True, False]  # the probes did get to call
    assert len(factory.created) == 3 and all(c.is_closed() for c in factory.created)
