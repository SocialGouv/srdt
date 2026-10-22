import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fake_api import FakeAPI, chunk

from retrieval_eval.cli import main
from retrieval_eval.data import Query, Ranking
from retrieval_eval.jsonl import append_jsonl
from retrieval_eval.pool import RANKINGS_FILE
from retrieval_eval.web_check import (
    COMPARE_FILE,
    PORT_FILE,
    REPORT_FILE,
    RESPONSES_FILE,
    PortRanking,
    WebAPIError,
    WebClient,
    WebResponse,
    check_snapshot,
    code_ids,
    compare,
    compare_lists,
    fiche_ids,
    idcc_count,
    jurisprudence,
    load_port,
    load_responses,
    snapshot_port_only,
    snapshot_queries,
)


def query(query_id: str = "q1", idcc: str | None = "1147") -> Query:
    return Query(
        query_id=query_id,
        text="Je suis prioritaire ?",
        source="idcc22",
        idcc=idcc,
        split="dev",
    )


def doc(doc_id: str, source: str = "fiches_service_public") -> dict:
    return {
        "content": "texte",
        "score": 1,
        "id_chunk": 1,
        "metadata": {"id": doc_id, "title": doc_id, "url": "", "source": source},
    }


def decision(doc_id: str, idx: int, score: float) -> dict:
    return {
        "content": "sommaire",
        "score": 0.5,
        "id_chunk": f"{doc_id}-{idx}",
        "rerank_score": score,
        "metadata": {"id": doc_id, "title": doc_id, "url": "", "source": "judilibre"},
    }


def body(
    fiches: list[str],
    idcc_chunks: int = 0,
    articles: tuple[str, ...] = (),
    decisions: tuple[dict, ...] = (),
    anonymized: str = "Je suis prioritaire ?",
) -> dict:
    chunks = [
        *(doc(d) for d in fiches),
        *(doc(a, "code_du_travail") for a in articles),
        *(doc(f"c{i}", "conventions") for i in range(idcc_chunks)),
        *decisions,
    ]
    return {
        "success": True,
        "data": {
            "anonymized": {"anonymized_question": anonymized},
            "localSearchChunks": chunks,
            "generated": {"text": "Réponse"},
        },
    }


def web(query_id: str = "q1", response: dict | None = None) -> WebResponse:
    return WebResponse(
        query_id=query_id,
        question="Je suis prioritaire ?",
        idcc="1147",
        status_code=200,
        response=response,
    )


def ranking(doc_ids: list[str], contributions: bool = True) -> Ranking:
    return Ranking(
        query_id="q1",
        variant="hybrid+rerank",
        doc_ids=doc_ids,
        scores=[None] * len(doc_ids),
        contributions=contributions,
    )


def port(doc_ids: list[str], contributions: bool = True) -> PortRanking:
    return PortRanking(
        **ranking(doc_ids, contributions).model_dump(), text="Je suis prioritaire ?"
    )


TOP = [f"d{i}" for i in range(10)]


# --- reading a response --------------------------------------------------------


def test_chunks_are_told_apart_by_source():
    chunks = body(
        ["a", "b"],
        idcc_chunks=2,
        articles=("L1",),
        decisions=(decision("j1", 0, 0.9), decision("j2", 3, 0.4)),
    )["data"]["localSearchChunks"]
    chunks.append(doc("x", "contributions"))
    chunks.append(doc("y", "contributions_idcc"))

    assert fiche_ids(chunks) == ["a", "b", "x"]  # generic contributions are fiches
    assert code_ids(chunks) == ["L1"]
    assert idcc_count(chunks) == 3  # conventions + contributions_idcc
    assert [(j["id"], j["id_chunk"]) for j in jurisprudence(chunks)] == [
        ("j1", "j1-0"),
        ("j2", "j2-3"),
    ]


def test_compare_lists_reports_order_set_and_overlap():
    same = compare_lists(TOP, TOP)
    assert same["identical"] and same["first_diff"] is None and same["overlap"] == 1

    swapped = compare_lists(TOP, ["d1", "d0", *TOP[2:]])
    assert not swapped["identical"] and swapped["same_set"]
    assert swapped["first_diff"] == 1

    replaced = compare_lists(TOP, [*TOP[:9], "z"])
    assert replaced["first_diff"] == 10
    assert replaced["gained"] == ["z"] and replaced["lost"] == ["d9"]
    assert replaced["overlap"] == pytest.approx(0.9)

    shorter = compare_lists(TOP, TOP[:8])  # /docs/retrieve returned 8 documents
    assert shorter["first_diff"] == 9 and not shorter["same_set"]


def test_compare_parity_drift_and_contributions():
    w = web(response=body(TOP, idcc_chunks=3))
    line = compare(query(), w, ranking(TOP, contributions=True), port(TOP, False))

    assert line["parity"]["identical"] and line["parity"]["contributions_equal"]
    # the stored run added the generic contributions, the web kept IDCC chunks
    assert line["drift"]["identical"] and not line["drift"]["contributions_equal"]
    assert line["web_idcc_chunks"] == 3 and not line["web_contributions"]
    assert not line["anonymize_changed"]


def test_compare_flags_a_changed_anonymisation_and_a_failed_call():
    w = web(response=body(TOP, anonymized="Je suis [PERSONNE] ?"))
    assert compare(query(), w, None, None)["anonymize_changed"]

    failed = web(response={"success": False, "error": "boom"})
    failed.error = "boom"
    line = compare(query(), failed, ranking(TOP), port(TOP))
    assert not line["web_ok"] and line["parity"] is None and line["drift"] is None


# --- snapshot (calls, faked) ---------------------------------------------------


class FakeWeb:
    def __init__(self, responses: dict[str, dict], statuses: list[int] | None = None):
        self.responses = responses  # question -> body
        self.statuses = statuses or []
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.calls.append(payload)
        if self.statuses:
            status = self.statuses.pop(0)
            return httpx.Response(status, json={"success": False, "error": "down"})
        return httpx.Response(200, json=self.responses[payload["question"]])

    def client(self) -> WebClient:
        http = httpx.AsyncClient(
            base_url="http://web", transport=httpx.MockTransport(self.handler)
        )
        return WebClient("http://web", "debug", client=http, backoff_s=0)


def fake_search_api() -> FakeAPI:
    chunks = [chunk(d, 1 - i / 100) for i, d in enumerate(TOP)]
    return FakeAPI(
        search_results={True: chunks},
        rerank_scores={d: 1 - i / 100 for i, d in enumerate(TOP)},
        idcc_chunks=[chunk("conv", 0.9)],
    )


def test_snapshot_saves_the_whole_response_and_ports_the_anonymized_text(tmp_path):
    response = body(TOP, idcc_chunks=1, anonymized="Texte anonymisé ?")
    fake_web = FakeWeb({"Je suis prioritaire ?": response})
    fake_api = fake_search_api()

    summary = asyncio.run(
        snapshot_queries(fake_web.client(), fake_api.api(), [query()], tmp_path)
    )

    assert summary.called == 1 and not summary.web_failed
    assert fake_web.calls == [
        {"question": "Je suis prioritaire ?", "agreementId": "1147"}
    ]
    saved = load_responses(tmp_path / RESPONSES_FILE)["q1"]
    assert saved.response == response  # entire body, generated text included
    assert {b["prompts"][0] for b in fake_api.routes("/search")} == {
        "Texte anonymisé ?"
    }
    ported = load_port(tmp_path / PORT_FILE)["q1"]
    assert ported.doc_ids == TOP and ported.text == "Texte anonymisé ?"
    assert not ported.contributions  # the IDCC pipeline selected a chunk


def test_snapshot_records_failures_and_resumes(tmp_path):
    fake_web = FakeWeb({"Je suis prioritaire ?": body(TOP)}, statuses=[500, 500])
    fake_api = fake_search_api()
    q = query(idcc=None)

    first = asyncio.run(
        snapshot_queries(fake_web.client(), fake_api.api(), [q], tmp_path)
    )
    assert first.web_failed == {"q1": "down"}  # one retry, then recorded
    assert not (tmp_path / PORT_FILE).exists()
    assert fake_web.calls[0] == {"question": "Je suis prioritaire ?"}  # no agreementId

    second = asyncio.run(
        snapshot_queries(fake_web.client(), fake_api.api(), [q], tmp_path)
    )
    assert second.called == 1 and not second.web_failed

    third = asyncio.run(
        snapshot_queries(fake_web.client(), fake_api.api(), [q], tmp_path)
    )
    assert third.skipped == 1 and third.called == 0
    assert len(fake_web.calls) == 3


def test_a_wrong_debug_key_stops_the_run(tmp_path):
    fake_web = FakeWeb({}, statuses=[401])
    with pytest.raises(WebAPIError, match="DEBUG_API_KEY"):
        asyncio.run(snapshot_queries(fake_web.client(), None, [query()], tmp_path))


# --- check (no call) -----------------------------------------------------------


@pytest.fixture
def run(tmp_path: Path, monkeypatch) -> Path:
    """A stored run and two snapshots on disk; any network call fails the test."""

    def no_network(*args, **kwargs):
        raise AssertionError("web-check made a network call")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    monkeypatch.setattr(httpx.Client, "send", no_network)

    append_jsonl(tmp_path / "queries.jsonl", [query("q1"), query("q2")])
    run_dir = tmp_path / "runs" / "r1"
    append_jsonl(
        run_dir / RANKINGS_FILE,
        [
            ranking(TOP, contributions=False),
            Ranking(**ranking(TOP).model_dump() | {"query_id": "q2"}),
        ],
    )
    for name, q2_top in (("20261020T100000Z", TOP), ("20261021T100000Z", TOP[::-1])):
        snap = run_dir / "web_snapshots" / name
        append_jsonl(
            snap / RESPONSES_FILE,
            [
                web("q1", body(TOP, idcc_chunks=1)),
                web("q2", body(q2_top, idcc_chunks=0)),
            ],
        )
        append_jsonl(
            snap / PORT_FILE,
            [
                port(TOP, contributions=False),
                PortRanking(**port(TOP).model_dump() | {"query_id": "q2"}),
            ],
        )
    return tmp_path


def cli(root: Path, *args: str) -> int:
    return main(
        [
            *args,
            "--queries",
            str(root / "queries.jsonl"),
            "--runs-dir",
            str(root / "runs"),
        ]
    )


def test_web_check_reads_files_only_and_writes_its_report(run, capsys):
    assert (
        cli(run, "web-check", "--run-id", "r1", "--snapshot", "20261020T100000Z") == 0
    )
    out = capsys.readouterr().out
    assert "parity: 2/2 identical" in out and "drift (same text): 2/2 identical" in out

    snap = run / "runs/r1/web_snapshots/20261020T100000Z"
    lines = [json.loads(x) for x in (snap / COMPARE_FILE).read_text().splitlines()]
    assert [x["query_id"] for x in lines] == ["q1", "q2"]
    assert "| q1 | ok |" in (snap / REPORT_FILE).read_text()


def test_web_check_defaults_to_the_latest_snapshot_and_fails_on_parity(run, capsys):
    # q2's web order is reversed in the latest snapshot while the port kept TOP
    assert cli(run, "web-check", "--run-id", "r1") == 1
    assert "parity: 1/2 identical" in capsys.readouterr().out


def test_web_check_against_an_earlier_snapshot(run, capsys):
    code = cli(run, "web-check", "--run-id", "r1", "--against", "20261020T100000Z")
    assert code == 1
    assert "drift (same text): 1/2 identical" in capsys.readouterr().out


def test_check_without_a_stored_run_compares_parity_only(run):
    snap = run / "runs/r1/web_snapshots/20261020T100000Z"
    lines = check_snapshot(snap, queries_path=run / "queries.jsonl", rankings_path=None)
    assert all(x["drift"] is None and x["parity"]["identical"] for x in lines)


def test_web_check_without_a_snapshot_is_a_one_line_error(run, capsys):
    assert cli(run, "web-check", "--run-id", "other") == 2
    assert "run `web-snapshot` first" in capsys.readouterr().err


def test_web_snapshot_without_the_web_settings_is_a_one_line_error(
    run, capsys, monkeypatch
):
    monkeypatch.delenv("WEB_BASE_URL", raising=False)
    monkeypatch.delenv("DEBUG_API_KEY", raising=False)
    monkeypatch.setattr("retrieval_eval.cli.load_dotenv", lambda *a, **k: None)
    assert cli(run, "web-snapshot", "--run-id", "r1", "--source", "idcc22") == 2
    assert "WEB_BASE_URL" in capsys.readouterr().err


def test_drift_leaves_out_the_queries_whose_text_anonymize_changed(run, capsys):
    snap = run / "runs/r1/web_snapshots/20261020T100000Z"
    responses = snap / RESPONSES_FILE
    lines = responses.read_text().splitlines()
    q2 = json.loads(lines[1])
    q2["response"] = body(TOP[::-1], anonymized="Je suis [PERSONNE] ?")
    responses.write_text(lines[0] + "\n" + json.dumps(q2) + "\n")

    cli(run, "web-check", "--run-id", "r1", "--snapshot", "20261020T100000Z")
    out = capsys.readouterr().out
    assert "drift (same text): 1/1 identical" in out
    assert "anonymize changed the text of 1 queries, drift not counted: q2" in out
    assert "| q2 | DIFF | 1 | text |" in (snap / REPORT_FILE).read_text()


def test_a_comparison_between_snapshots_keeps_the_one_with_the_stored_run(run):
    cli(run, "web-check", "--run-id", "r1")
    snap = run / "runs/r1/web_snapshots/20261021T100000Z"
    report = (snap / REPORT_FILE).read_text()

    cli(run, "web-check", "--run-id", "r1", "--against", "20261020T100000Z")
    assert (snap / REPORT_FILE).read_text() == report
    assert (snap / "report-vs-20261020T100000Z.md").exists()
    assert (snap / "compare-vs-20261020T100000Z.jsonl").exists()


# --- port-only snapshots -------------------------------------------------------


def test_port_only_snapshot_anonymizes_with_the_api_and_resumes(tmp_path):
    fake_api = fake_search_api()
    q = query().model_copy(update={"text": "Monsieur, suis-je prioritaire ?"})

    first = asyncio.run(snapshot_port_only(fake_api.api(), [q], tmp_path))
    assert first.called == 1 and not (tmp_path / RESPONSES_FILE).exists()
    assert fake_api.routes("/anonymize") == [
        {"user_question": "Monsieur, suis-je prioritaire ?"}
    ]
    ported = load_port(tmp_path / PORT_FILE)["q1"]
    assert ported.text == "PERSONNE, suis-je prioritaire ?"
    assert {b["prompts"][0] for b in fake_api.routes("/search")} == {ported.text}

    second = asyncio.run(snapshot_port_only(fake_api.api(), [q], tmp_path))
    assert second.skipped == 1 and len(fake_api.routes("/anonymize")) == 1


def port_only_snapshot(run: Path, name: str, q2_top: list[str], text: str) -> Path:
    snap = run / "runs/r1/web_snapshots" / name
    append_jsonl(
        snap / PORT_FILE,
        [
            PortRanking(
                **port(TOP, False).model_dump() | {"text": "Je suis prioritaire ?"}
            ),
            PortRanking(**port(q2_top).model_dump() | {"query_id": "q2", "text": text}),
        ],
    )
    return snap


def test_a_port_only_snapshot_is_checked_against_the_stored_run(run, capsys):
    port_only_snapshot(run, "20261022T100000Z", TOP[::-1], "Je suis prioritaire ?")

    assert cli(run, "web-check", "--run-id", "r1") == 0  # latest; no parity to fail
    out = capsys.readouterr().out
    assert "parity" not in out
    assert "drift (same text): 1/2 identical" in out


def test_a_port_only_snapshot_against_a_web_snapshot_compares_the_ports(run, capsys):
    # the baseline's port ranked q2 with TOP on the stored text; here q2 ran on
    # another anonymized text
    port_only_snapshot(run, "20261022T100000Z", TOP, "Je suis [PERSONNE] ?")

    code = cli(run, "web-check", "--run-id", "r1", "--against", "20261020T100000Z")
    out = capsys.readouterr().out
    assert "drift (same text): 1/1 identical" in out
    assert "drift not counted: q2" in out
    assert code == 0
