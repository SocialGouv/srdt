import base64
import json
import unicodedata

import pytest
from cryptography.exceptions import InvalidTag
from test_answer_labelling import (
    CRITERIA,
    GENERATORS,
    NODE,
    answer,
    run_node,
    world,
)

from answer_eval.cli import main
from answer_eval.labelling import KEY_FILE, Key, build_data
from answer_eval.publish import (
    ITERATIONS,
    PublishError,
    check_target,
    decrypt_secret,
    encrypt_secret,
    publish,
)

TOKEN = "github_pat_11ABCDEFG0_not-a-real-token-but-long-enough"
PASSWORD = "cheval « été » batterie agrafe"  # composed accents (NFC)

needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def distinct_world():
    """The world of the labelling tests, with answers easy to look for."""
    contexts, answers = world()
    answers = [
        a.model_copy(update={"answer": f"Texte unique n° {i}"})
        for i, a in enumerate(answers)
    ]
    return contexts, answers


def test_python_round_trip_and_parameters():
    vault = encrypt_secret(TOKEN, PASSWORD, iterations=1000)
    assert decrypt_secret(vault, PASSWORD) == TOKEN
    assert decrypt_secret(vault, unicodedata.normalize("NFD", PASSWORD)) == TOKEN
    with pytest.raises(InvalidTag):
        decrypt_secret(vault, PASSWORD + "x")
    assert len(base64.b64decode(vault["salt"])) == 16
    assert len(base64.b64decode(vault["iv"])) == 12
    # the GCM tag (16 bytes) follows the ciphertext, as WebCrypto expects
    assert len(base64.b64decode(vault["ciphertext"])) == len(TOKEN) + 16
    assert ITERATIONS == 600_000
    again = encrypt_secret(TOKEN, PASSWORD, iterations=1000)
    assert again["salt"] != vault["salt"] and again["iv"] != vault["iv"]


@needs_node
def test_webcrypto_decrypts_the_python_vault():
    vault = encrypt_secret(TOKEN, PASSWORD)  # the real iteration count
    out = run_node(
        f"""
        const vault = {json.dumps(vault)};
        (async () => {{
          const ok = await decryptVault(vault, {json.dumps(PASSWORD)});
          const nfd = await decryptVault(
            vault, {json.dumps(PASSWORD)}.normalize('NFD'));
          let wrong = null;
          try {{ await decryptVault(vault, 'mauvais'); }}
          catch (e) {{ wrong = {{message: e.message, flag: e.wrongPassword}}; }}
          console.log(JSON.stringify({{ok, nfd, wrong}}));
        }})().catch((e) => {{ console.error(e); process.exit(1); }});
        """
    )
    r = json.loads(out)
    assert r["ok"] == TOKEN and r["nfd"] == TOKEN
    assert r["wrong"] == {"message": "Mot de passe incorrect.", "flag": True}


def test_published_page_holds_no_data_and_no_secret(tmp_path):
    contexts, answers = distinct_world()
    data, key, _ = build_data("run", contexts, answers, CRITERIA, seed=2)
    page, data_file = publish(
        data,
        tmp_path / "out",
        repo="owner/labels-data",
        data_path="data.json",
        password=PASSWORD,
        token=TOKEN,
        iterations=1000,
    )
    assert page == tmp_path / "out/page/index.html"
    assert data_file == tmp_path / "out/data/data.json"
    html = page.read_text(encoding="utf-8")
    for secret in (TOKEN, PASSWORD, "Question q1", "Texte unique", *GENERATORS):
        assert secret not in html
    assert '<script type="application/json" id="data">null</script>' in html
    start = html.index('<script type="application/json" id="vault">') + len(
        '<script type="application/json" id="vault">'
    )
    vault = json.loads(html[start : html.index("</script>", start)])
    assert (vault["repo"], vault["data_path"]) == ("owner/labels-data", "data.json")
    assert decrypt_secret(vault, PASSWORD) == TOKEN

    hosted = data_file.read_text(encoding="utf-8")
    assert json.loads(hosted) == data
    assert "Texte unique" in hosted and "Question q1" in hosted
    for name in GENERATORS:
        assert name not in hosted
    assert "item_id" not in hosted and "::" not in hosted
    assert not list((tmp_path / "out").rglob(KEY_FILE))
    assert {i.generator for i in key.items} == set(GENERATORS)


def test_targets_are_checked():
    check_target("owner/repo.name", "dir/data-1.json")
    for repo, path in [
        ("owner", "data.json"),
        ("owner/repo/x", "data.json"),
        ("owner/repo", "../data.json"),
        ("owner/repo", "/data.json"),
        ("owner/repo", "data.txt"),
    ]:
        with pytest.raises(PublishError):
            check_target(repo, path)


def write_run(runs_dir, generators=GENERATORS):
    contexts, answers = distinct_world()
    run = runs_dir / "r"
    run.mkdir(parents=True)
    (run / "contexts.jsonl").write_text(
        "".join(c.model_dump_json() + "\n" for c in contexts), encoding="utf-8"
    )
    answers.append(answer("glm-secret+32k", "q1", "Texte unique variante"))
    (run / "answers.jsonl").write_text(
        "".join(a.model_dump_json() + "\n" for a in answers), encoding="utf-8"
    )
    models = runs_dir.parent / "generators.toml"
    models.write_text(
        '[providers.p]\nbase_url = "http://x/v1"\n'
        + "".join(
            f'[[models]]\nprovider = "p"\nmodel = "m{i}"\nname = "{g}"\n'
            for i, g in enumerate(generators)
        ),
        encoding="utf-8",
    )
    return run, models


def test_label_publish_cli(tmp_path, monkeypatch, capsys):
    run, models = write_run(tmp_path / "runs", GENERATORS[:2])
    args = ["--runs-dir", str(tmp_path / "runs"), "label-publish", "--run-id", "r"]
    args += ["--models", str(models), "--repo", "owner/data"]

    # the developer's eval/.env may hold real secrets: keep it out
    monkeypatch.setattr("answer_eval.cli.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("LABEL_PASSWORD", raising=False)
    monkeypatch.setenv("LABEL_GITHUB_TOKEN", TOKEN)
    assert main([*args, "--out", str(tmp_path / "out")]) == 2
    assert "LABEL_PASSWORD" in capsys.readouterr().err

    monkeypatch.setenv("LABEL_PASSWORD", PASSWORD)
    assert main([*args, "--out", str(tmp_path / "runs")]) == 2  # would hold key.json
    assert "would hold key.json" in capsys.readouterr().err

    assert main([*args, "--out", str(tmp_path / "out")]) == 0
    captured = capsys.readouterr()
    assert "Left out (not in generators.toml): gpt-oss-secret" in captured.err
    assert TOKEN not in captured.err + captured.out
    assert PASSWORD not in captured.err + captured.out

    key = Key.model_validate_json((run / "labelling" / KEY_FILE).read_text())
    assert {i.generator for i in key.items} == set(GENERATORS[:2])
    assert any(i.item_id == "glm-secret+32k::q1" for i in key.items)  # the variant
    assert len(key.questions) == 2
    assert not list((tmp_path / "out").rglob(KEY_FILE))
    data = json.loads((tmp_path / "out/data/data.json").read_text(encoding="utf-8"))
    assert [len(q["answers"]) for q in data["questions"]] == [2, 2]
    assert "gpt-oss" not in json.dumps(data)
    html = (tmp_path / "out/page/index.html").read_text(encoding="utf-8")
    assert TOKEN not in html and "Texte unique" not in html

    assert main([*args, "--out", str(tmp_path / "out")]) == 2  # key exists
    assert "--force" in capsys.readouterr().err
    assert main([*args, "--out", str(tmp_path / "out"), "--force"]) == 0


def test_label_export_keeps_only_the_configured_models(tmp_path, capsys):
    run, models = write_run(tmp_path / "runs", [GENERATORS[0], GENERATORS[2]])
    assert (
        main(
            [
                "--runs-dir",
                str(tmp_path / "runs"),
                "label-export",
                "--run-id",
                "r",
                "--models",
                str(models),
            ]
        )
        == 0
    )
    assert "Left out (not in generators.toml): glm-secret" in capsys.readouterr().err
    key = Key.model_validate_json((run / "labelling" / KEY_FILE).read_text())
    assert {i.generator for i in key.items} == {GENERATORS[0], GENERATORS[2]}
    html = (run / "labelling" / "answers-labelling.html").read_text(encoding="utf-8")
    assert "variante" not in html


@needs_node
def test_hosted_helpers_with_a_stubbed_github():
    out = run_node(
        """
        const files = {'labels/remi.csv': {text: 'avant', sha: 'sha1'}};
        const calls = [];
        let conflicts = 1;
        const reply = (status, body) => ({
          ok: status < 300, status,
          json: async () => body, text: async () => JSON.stringify(body),
        });
        async function fetchStub(url, opts = {}) {
          const method = opts.method || 'GET';
          const path = decodeURIComponent(url.split('/contents/')[1]);
          calls.push({url, method, accept: opts.headers.Accept,
                      auth: opts.headers.Authorization, cache: opts.cache || null,
                      sha: opts.body ? JSON.parse(opts.body).sha || null : null});
          if (path === 'data.json') {
            if (opts.headers.Authorization !== 'Bearer tok') return reply(401, {});
            return {ok: true, status: 200, text: async () => '{"title": "t"}'};
          }
          const file = files[path];
          if (method === 'GET') {
            if (!file) return reply(404, {});
            // GitHub wraps the base64 content in lines
            const content = utf8ToB64(file.text).replace(/(.{8})/g, '$1\\n');
            return reply(200, {sha: file.sha, content, encoding: 'base64'});
          }
          const body = JSON.parse(opts.body);
          if (conflicts > 0) {  // another tab saved first
            conflicts--;
            files[path] = {text: 'autre onglet', sha: 'sha2'};
            return reply(409, {});
          }
          const stale = file ? body.sha !== file.sha : !!body.sha;
          if (stale) return reply(409, {});
          files[path] = {text: b64ToUtf8(body.content), sha: 'sha' + calls.length};
          return reply(file ? 200 : 201, {content: {sha: files[path].sha}});
        }
        (async () => {
          const api = githubApi(fetchStub, 'owner/data', 'tok');
          const raw = await api.getRaw('data.json');
          const missing = await api.getFile('labels/personne.csv');
          const seen = [];
          const content = (remote) => {
            seen.push(remote);
            return remote ? 'fusion « ' + remote.text + ' »' : 'première';
          };
          const sha = await saveLabelsFile(
            api, 'labels/remi.csv', 'sha1', content, 'm');
          const file = files['labels/remi.csv'].text;
          const created = await saveLabelsFile(
            api, 'labels/élodie.csv', null, () => 'é', 'm');
          conflicts = 2;
          let twice = null;
          try { await saveLabelsFile(api, 'labels/remi.csv', sha, () => 'x', 'm'); }
          catch (e) { twice = e.status; }
          let denied = null;
          try { await githubApi(fetchStub, 'owner/data', 'bad').getRaw('data.json'); }
          catch (e) { denied = e.message; }
          const local = {
            A: {values: {s: 'Oui'}}, B: {values: {s: 'Oui'}}, C: {values: {s: 'Oui'}},
            D: {values: {s: 'Non'}},
          };
          const remote = {A: {values: {s: 'Non'}}, B: {values: {s: 'Non'}},
                          E: {values: {s: 'Non'}}};
          console.log(JSON.stringify({
            raw, missing, seen, sha, created, twice, denied, file,
            accented: files['labels/élodie.csv'].text,
            calls: calls.slice(0, 5),
            merged: mergeLabels(local, remote, new Set(['A', 'D'])),
            noRemote: mergeLabels(local, null, new Set()),
            path: LABELS_PATH,
            b64: utf8ToB64('é « ü » 😀'),
            back: b64ToUtf8(utf8ToB64('é « ü » 😀')),
          }));
        })().catch((e) => { console.error(e); process.exit(1); });
        """
    )
    r = json.loads(out)
    assert r["raw"] == '{"title": "t"}'
    assert r["missing"] is None
    # a 409, then the file read again, merged by the caller, and written
    assert r["seen"] == [None, {"text": "autre onglet", "sha": "sha2"}]
    assert r["file"] == "fusion « autre onglet »"
    assert r["sha"].startswith("sha") and r["sha"] not in ("sha1", "sha2")
    assert r["accented"] == "é" and r["created"]
    assert r["twice"] == 409  # one retry only
    assert "jeton" in r["denied"]
    base = "https://api.github.com/repos/owner/data/contents/"
    assert r["calls"][0] == {
        "url": base + "data.json",
        "method": "GET",
        "accept": "application/vnd.github.raw+json",
        "auth": "Bearer tok",
        "cache": "no-store",
        "sha": None,
    }
    assert r["calls"][1]["accept"] == "application/vnd.github+json"
    assert [(c["method"], c["sha"]) for c in r["calls"][2:5]] == [
        ("PUT", "sha1"),
        ("GET", None),
        ("PUT", "sha2"),
    ]
    assert r["merged"] == {
        "A": {"values": {"s": "Oui"}},  # changed here: local
        "B": {"values": {"s": "Non"}},  # saved elsewhere since: remote
        "D": {"values": {"s": "Non"}},  # changed here, not saved yet
        "E": {"values": {"s": "Non"}},
    }  # C: saved, then cleared elsewhere: dropped
    assert set(r["noRemote"]) == {"A", "B", "C", "D"}
    assert r["path"] == "labels.json"
    assert r["b64"] == base64.b64encode("é « ü » 😀".encode()).decode()
    assert r["back"] == "é « ü » 😀"


@needs_node
def test_labels_json_round_trip_in_the_page():
    out = run_node(
        """
        const criteria = ['correct_en_droit', 'suffisant', 'intelligible'];
        const ids = ['01-A', '01-B', '01-Q'];
        const labels = {
          '01-A': {values: {correct_en_droit: 'Oui', suffisant: 'Non'},
                   comment: 'à « revoir »', flag: true, seconds: 31.6},
          '01-B': {values: {}, comment: '', flag: false, seconds: 0},
          '01-Q': {values: {sources_suffisantes: 'Non'}, comment: 'CC absente'},
        };
        const text = buildLabelsJson(ids, labels, criteria,
                                     {dataset_id: 'd1'});
        console.log(JSON.stringify({
          doc: JSON.parse(text),
          back: labelsFromJson(text, new Set(ids), criteria, ['Oui', 'Non'], 'd1'),
          other: labelsFromJson(text, new Set(ids), criteria, ['Oui', 'Non'], 'd2'),
          stable: text === buildLabelsJson(ids, labels, criteria,
                                           {dataset_id: 'd1'}),
        }));
        """
    )
    r = json.loads(out)
    assert r["doc"] == {
        "format": "answers-labelling/1",
        "dataset_id": "d1",
        "labels": {
            "01-A": {
                "correct_en_droit": "Oui",
                "suffisant": "Non",
                "comment": "à « revoir »",
                "flag": True,
                "seconds": 32,
            },
            "01-Q": {"sources_suffisantes": "Non", "comment": "CC absente"},
        },
    }
    assert r["back"]["applied"] == 2
    assert r["back"]["labels"]["01-Q"]["values"] == {"sources_suffisantes": "Non"}
    assert r["other"]["applied"] == 0  # labels of another build of the page
    assert r["stable"]


def test_label_import_reads_the_labels_of_the_data_repo(tmp_path, monkeypatch, capsys):
    import httpx

    import answer_eval.cli as cli
    from answer_eval.publish import fetch_labels

    run, models = write_run(tmp_path / "runs", GENERATORS[:2])
    monkeypatch.setenv("LABEL_PASSWORD", PASSWORD)
    monkeypatch.setenv("LABEL_GITHUB_TOKEN", TOKEN)
    base = ["--runs-dir", str(tmp_path / "runs")]
    publish_args = ["label-publish", "--run-id", "r", "--models", str(models)]
    publish_args += ["--repo", "owner/data", "--out", str(tmp_path / "out")]
    assert main([*base, *publish_args, "--annotator", "elodie"]) == 0
    html = (tmp_path / "out/page/index.html").read_text(encoding="utf-8")
    assert "elodie" not in html  # the name stays local
    key = Key.model_validate_json((run / "labelling" / KEY_FILE).read_text())
    first = key.items[0].label_id

    doc = {
        "format": "answers-labelling/1",
        "dataset_id": key.dataset_id,
        "labels": {
            first: {"correct_en_droit": "Oui", "suffisant": "Non"}
            | {"intelligible": "Oui", "seconds": 12},
            "01-Q": {"sources_suffisantes": "Non", "comment": "CC absente"},
        },
    }
    repo = {"labels.json": json.dumps(doc, ensure_ascii=False).encode()}
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"]))
        name = request.url.path.rsplit("/", 1)[-1]
        if name not in repo:
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, content=repo[name])

    def fake_fetch(repo_name, token, dest):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return fetch_labels(repo_name, token, dest, client)

    monkeypatch.setattr(cli, "fetch_labels", fake_fetch)
    capsys.readouterr()
    assert main([*base, "label-import", "--run-id", "r"]) == 0
    assert "elodie: 1/" in capsys.readouterr().err
    assert seen == [
        (
            "https://api.github.com/repos/owner/data/contents/labels.json",
            f"Bearer {TOKEN}",
        )
    ]
    labelling = run / "labelling"
    (label,) = [
        json.loads(line)
        for line in (labelling / "human-elodie.jsonl").read_text().splitlines()
    ]
    assert label["labels"] == {
        "correct_en_droit": True,
        "suffisant": False,
        "intelligible": True,
    }
    assert label["seconds"] == 12
    (question,) = [
        json.loads(line)
        for line in (labelling / "question-labels-elodie.jsonl")
        .read_text()
        .splitlines()
    ]
    assert (question["sources_suffisantes"], question["comment"]) == (
        False,
        "CC absente",
    )

    # labels of another build of the page are refused
    repo["labels.json"] = repo["labels.json"].replace(
        key.dataset_id.encode(), b"0000000000"
    )
    assert main([*base, "label-import", "--run-id", "r"]) == 2
    assert "another build of the page" in capsys.readouterr().err

    # nothing saved yet
    del repo["labels.json"]
    assert main([*base, "label-import", "--run-id", "r"]) == 0
    assert "No labels in owner/data yet" in capsys.readouterr().err
