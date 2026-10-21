import json

import pytest
from conftest import make_item

from judge_eval.cli import _describe_probes, _select_models, _spread, main
from judge_eval.endpoints import ModelCheck, ModelProbe
from judge_eval.judge import ModelConfig, Verdict


def test_spread_picks_items_across_the_dataset():
    items = [make_item(f"id_{i}", question_id=i // 10) for i in range(100)]
    picked = _spread(items, 5)
    assert len(picked) == 5
    assert len({i.question_id for i in picked}) == 5
    assert len(_spread(items[:3], 10)) == 3  # asking for more than exists


def test_setup_errors_are_one_line_messages_not_tracebacks(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    models = tmp_path / "models.toml"
    models.write_text(
        '[providers.p]\nbase_url = "http://x/v1"\napi_key_env = "MISSING_KEY"\n'
        '[[models]]\nprovider = "p"\nmodel = "m"\n'
    )
    dataset = tmp_path / "data.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "id": "a",
                    "question": "Q",
                    "reponse": "R",
                    "correct_en_droit": "Oui",
                    "suffisant": "Oui",
                    "intelligible": "Oui",
                }
            ]
        )
    )
    code = main(
        [
            "run", "--run-id", "t", "--models", str(models),
            "--dataset", str(dataset), "--runs-dir", str(tmp_path / "runs"),
        ]
    )  # fmt: skip
    assert code == 2
    assert "MISSING_KEY" in capsys.readouterr().err
    assert not (tmp_path / "runs" / "t").exists()  # failed before creating the run


def _models_file(tmp_path, models=("wanted-model",)):
    path = tmp_path / "models.toml"
    entries = "".join(f'[[models]]\nprovider = "p"\nmodel = "{m}"\n' for m in models)
    path.write_text('[providers.p]\nbase_url = "http://x/v1"\n' + entries)
    return path


def _dataset_file(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "a",
                    "question": "Q",
                    "reponse": "R",
                    "correct_en_droit": "Oui",
                    "suffisant": "Oui",
                    "intelligible": "Oui",
                }
            ]
        )
    )
    return path


def _fake_check(available):
    async def check(configs, client_factory=None):
        return [ModelCheck(c, available) for c in configs]

    return check


def test_run_stops_before_any_call_when_a_model_id_is_not_served(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("judge_eval.cli.check_models", _fake_check({"other-model"}))
    code = main(
        [
            "run", "--run-id", "t", "--models", str(_models_file(tmp_path)),
            "--dataset", str(_dataset_file(tmp_path)),
            "--runs-dir", str(tmp_path / "r"),
        ]
    )  # fmt: skip
    err = capsys.readouterr().err
    assert code == 2
    assert "NOT SERVED" in err and "other-model" in err and "--skip-check" in err
    assert not (tmp_path / "r" / "t").exists()


def test_models_command_groups_models_by_endpoint(tmp_path, monkeypatch, capsys):
    models = _models_file(tmp_path, ("wanted-model", "other-wanted"))
    monkeypatch.setattr(
        "judge_eval.cli.check_models",
        _fake_check({"wanted-model", "other-wanted", "b"}),
    )
    assert main(["models", "--models", str(models), "--all"]) == 0
    out = capsys.readouterr().out
    assert out.count("http://x/v1") == 1  # one block for the shared endpoint
    assert "OK          wanted-model" in out and "OK          other-wanted" in out
    assert "available (3): b, other-wanted, wanted-model" in out

    monkeypatch.setattr("judge_eval.cli.check_models", _fake_check({"wanted-model"}))
    assert main(["models", "--models", str(models)]) == 1
    out = capsys.readouterr().out
    assert "NOT SERVED  other-wanted" in out
    assert "available (1): wanted-model" in out  # listed because one is missing


def test_only_selects_by_model_name_or_provider(tmp_path):
    path = tmp_path / "models.toml"
    path.write_text(
        '[providers.a]\nbase_url = "http://a/v1"\n'
        '[providers.b]\nbase_url = "http://b/v1"\n'
        '[[models]]\nprovider = "a"\nmodel = "m1"\n'
        '[[models]]\nprovider = "a"\nmodel = "m2"\n'
        '[[models]]\nprovider = "b"\nmodel = "m3"\n'
    )
    names = lambda only: [c.name for c in _select_models(path, only)]  # noqa: E731
    assert names(None) == ["a/m1", "a/m2", "b/m3"]
    assert names("a") == ["a/m1", "a/m2"]  # a whole provider
    assert names("a/m2,b") == ["a/m2", "b/m3"]  # mix of model and provider
    with pytest.raises(ValueError, match="Unknown model or provider"):
        names("c")


def _probe(name, status="ok", label=True, **verdict):
    return ModelProbe(
        ModelConfig(name=name, base_url="http://x/v1", model=name),
        Verdict(status=status, label=label, **verdict),
    )


def test_probe_table_shows_each_model_and_explains_failures():
    probes = [
        _probe("good", response_mode="json_schema", finish_reason="stop",
               latency_s=1.234, completion_tokens=42, served_model="good-2025"),
        _probe("garbled", status="parse_error", label=None, raw="", error="no JSON",
               finish_reason="length", latency_s=30.0, completion_tokens=4096),
        _probe("down", status="api_error", label=None, error="APIError: boom"),
        ModelProbe(
            ModelConfig(name="nokey", base_url="http://x/v1", model="nokey"),
            skipped="Environment variable KEYVAR is not set",
        ),
    ]  # fmt: skip
    text = _describe_probes(probes)
    rows = {line.split()[0]: line for line in text.splitlines() if line.strip()}
    assert "ok (Oui)" in rows["good"] and "json_schema" in rows["good"]
    assert "1.2s" in rows["good"] and "good-2025" in rows["good"]
    assert "PARSE ERROR" in rows["garbled"] and "length" in rows["garbled"]
    assert "API ERROR" in rows["down"]
    assert "NOT CALLED" in rows["nokey"]
    # Details of every failure, and a hint for the cut-off reply.
    assert "down: APIError: boom" in text
    assert "nokey: Environment variable KEYVAR is not set" in text
    assert "max_tokens" in text
    assert text.endswith("1/4 model(s) OK")


def test_check_command_exit_code_follows_the_probes(tmp_path, monkeypatch, capsys):
    models, dataset = _models_file(tmp_path), _dataset_file(tmp_path)
    seen = {}

    def fake_probe(outcome):
        async def probe(configs, item, criterion, prompts):
            seen.update(
                models=[c.name for c in configs], item=item.id, criterion=criterion
            )
            return [outcome(c.name) for c in configs]

        return probe

    args = ["check", "--models", str(models), "--dataset", str(dataset)]
    monkeypatch.setattr("judge_eval.cli.probe_models", fake_probe(_probe))
    assert main(args) == 0
    assert seen == {
        "models": ["p/wanted-model"], "item": "a", "criterion": "correct_en_droit",
    }  # fmt: skip
    assert "1/1 model(s) OK" in capsys.readouterr().out

    failing = lambda name: _probe(name, "api_error", None, error="boom")  # noqa: E731
    monkeypatch.setattr("judge_eval.cli.probe_models", fake_probe(failing))
    assert main(args) == 1

    assert main([*args, "--item", "nope"]) == 2
    assert "Unknown item id" in capsys.readouterr().err
