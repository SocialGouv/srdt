import json
from pathlib import Path

import pytest

from acco_analysis import accords_site, crypto_site
from acco_analysis.accords_site import (
    build_agreement,
    build_site,
    line_marks,
    locate,
    memberships,
    sync_to_repo,
)
from acco_analysis.corpus import Agreement

QUOTE = "En cas de canicule, l'employeur peut imposer le télétravail"


def agreement(text: str, i: str = "ACCOTEXT1") -> Agreement:
    return Agreement(
        id=i,
        title="Accord <b>chaleur</b>",
        company="ACME",
        siret=None,
        sector="Bâtiment",
        idcc="1596",
        nature="ACCORD",
        signed="2024-05-01",
        text=text,
    )


TEXT = "\n".join(
    [
        "Article 1 – Objet",
        "Le présent accord porte sur le temps de travail des salariés.",
        "Article 2 – Canicule",
        "Les horaires sont revus.",
        f"{QUOTE} lorsque la vigilance est déclenchée.",
        "Article 3 – Durée",
        "L'accord est conclu pour une durée indéterminée.",
    ]
)


def test_locate_ignores_case_spacing_and_accent_encoding():
    text = "Avant.  EN CAS de   canicule, l'employeur peut imposer le télétravail."
    start, stop = locate(text, QUOTE) or (0, 0)
    assert text[start:stop].startswith("EN CAS de   canicule")
    assert text[start:stop].endswith("télétravail")


def test_locate_misses_and_short_quotes_give_none():
    assert locate("autre chose entièrement, sans rapport avec le sujet", QUOTE) is None
    assert locate(QUOTE, "canicule") is None  # too short to be a safe match


def test_locate_strips_the_quotation_marks_and_ellipsis_of_the_quote():
    assert locate(QUOTE, f"« {QUOTE}… »") == (0, len(QUOTE))


def test_line_marks_split_a_span_over_lines():
    lines = ["abc def", "ghi jkl", "mno"]
    # "def\nghi jk" is characters 4 to 14 of "abc def\nghi jkl\nmno"
    assert line_marks(lines, 0, 3, (4, 14)) == [[0, 4, 7], [1, 0, 6]]
    assert line_marks(lines, 1, 3, (0, 3)) == [[1, 0, 3]]


def passage(n: int, start: int, stop: int) -> dict:
    return {"id": f"ACCOTEXT1-{n}", "section": n, "start": start, "stop": stop}


def test_build_agreement_marks_passages_and_quotes():
    page, found, missed = build_agreement(
        agreement(TEXT),
        [passage(2, 0, 2)],
        [{"family": "telework", "label": "Télétravail", "nuance": None}],
        [
            {"id": "ACCOTEXT1-2", "quote": QUOTE},
            {"id": "ACCOTEXT1-2", "quote": "une phrase qui n'est pas dans le texte"},
        ],
    )
    assert (found, missed) == (1, 1)
    by_n = {s["n"]: s for s in page["sections"]}
    assert by_n[2]["h"] == "Article 2 – Canicule" or by_n[2]["h"].endswith("Canicule")
    assert by_n[2]["heat"] == [[0, 2]] and by_n[1]["heat"] == []
    assert by_n[2]["marks"] == [[1, 0, len(QUOTE)]]
    assert page["company"] == "ACME" and page["badges"][0]["family"] == "telework"


def test_old_passages_without_a_range_cover_their_whole_section():
    page, _, _ = build_agreement(
        agreement(TEXT), [{"id": "ACCOTEXT1-2", "section": 2}], [], []
    )
    section = next(s for s in page["sections"] if s["n"] == 2)
    assert section["heat"] == [[0, len(section["lines"])]]


def sample_flavours() -> dict:
    return {
        "snapshot": "s1",
        "families": {
            "telework": {
                "label": "Télétravail",
                "strict": 2,
                "loose": 2,
                "constant": [],
                "min_support": 10,
                "flavours": [
                    {
                        "id": "telework-1",
                        "rank": 1,
                        "name": "N",
                        "description": "d",
                        "variations": [],
                        "strict": 1,
                        "loose": 1,
                        "collapsed": 1,
                        "distributions": {},
                        "top_sectors": [],
                        "codes": [{"item": "x:y", "label": "y"}],
                        "agreements": ["ACCOTEXT1"],
                        "quotes": [
                            {
                                "id": "ACCOTEXT1-2",
                                "quote": QUOTE,
                                "company": "ACME",
                                "signed": "2024-05-01",
                                "url": "https://www.legifrance.gouv.fr/acco/id/ACCOTEXT1",
                            }
                        ],
                    }
                ],
                "other": {"agreements": ["ACCOTEXT2"], "distributions": {}},
            },
            "hours": {
                "label": "Horaires",
                "strict": 0,
                "loose": 0,
                "constant": [],
                "min_support": 10,
                "flavours": [],
                "other": {"agreements": [], "distributions": {}},
            },
        },
    }


def test_memberships_give_nuance_other_and_loose_only_badges():
    loose = {
        "ACCOTEXT1": {"families": ["telework", "hours"]},
        "ACCOTEXT2": {"families": ["telework"]},
    }
    badges = memberships(sample_flavours(), loose)
    assert badges["ACCOTEXT1"][0]["nuance"] == {
        "id": "telework-1",
        "rank": 1,
        "name": "N",
    }
    assert badges["ACCOTEXT1"][1] == {
        "family": "hours",
        "label": "Horaires",
        "nuance": None,
        "loose_only": True,
    }
    assert badges["ACCOTEXT2"] == [
        {"family": "telework", "label": "Télétravail", "nuance": None}
    ]


def build(out: Path, password: str | None = None, report=None) -> dict[str, int]:
    agreements = [
        agreement(TEXT),
        agreement("Article 1 – X\nAutre texte.", "ACCOTEXT2"),
    ]
    metrics = {
        "dataset": {
            k: 1
            for k in ("passages_coded", "template_groups", "agreements_in_a_template")
        }
    }
    profile = {"template": None, "families": ["telework"]}
    profiles = {
        "strict": {"ACCOTEXT1": profile, "ACCOTEXT2": profile},
        "loose": {"ACCOTEXT1": profile, "ACCOTEXT2": profile},
    }
    passages = [
        {**passage(2, 0, 2), "agreement_id": "ACCOTEXT1"},
        {"id": "ACCOTEXT2-0", "agreement_id": "ACCOTEXT2", "section": 0},
    ]
    return build_site(
        out,
        password=password,
        flavours=sample_flavours(),
        metrics=metrics,
        agreements=agreements,
        profiles=profiles,
        passages=passages,
        iterations=1000,
        report=report,
    )


def test_plain_site_has_a_page_per_placed_agreement_and_links_to_them(tmp_path: Path):
    out = tmp_path / "site"
    summary = build(out)
    assert summary == {"agreements": 2, "quotes_found": 1, "quotes_missed": 0}
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["encrypted"] is False
    assert {"index.html", "accord.html", "gate.js"} <= {p.name for p in out.iterdir()}
    app = (out / "data" / "app.dat").read_text()
    salt = bytes.fromhex(manifest["salt"])
    key = crypto_site.file_key(salt, "ACCOTEXT1")
    assert f'"{key}"' in app
    page = json.loads((out / "data" / f"{key}.dat").read_text())
    assert page["title"] == "Accord <b>chaleur</b>"  # raw data: the page escapes it


def test_encrypted_site_has_no_readable_content_nor_ids(tmp_path: Path):
    out = tmp_path / "site-enc"
    build(out, "a long enough passphrase")
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["encrypted"] is True and manifest["iterations"] == 1000
    files = [p for p in out.rglob("*") if p.is_file()]
    for f in files:
        assert b"canicule" not in f.read_bytes().lower()
        assert b"ACCOTEXT" not in f.read_bytes() and "ACCOTEXT" not in f.name
    salt = bytes.fromhex(manifest["salt"])
    key = crypto_site.derive_key("a long enough passphrase", salt, 1000)
    blob = (
        out / "data" / f"{crypto_site.file_key(salt, 'ACCOTEXT1')}.dat"
    ).read_bytes()
    assert json.loads(crypto_site.decrypt(key, blob))["id"] == "ACCOTEXT1"


def test_rebuilding_leaves_no_stale_files(tmp_path: Path):
    out = tmp_path / "site"
    build(out)
    (out / "data" / "stale.dat").write_text("x")
    build(out)
    assert not (out / "data" / "stale.dat").exists()


def test_sync_refuses_a_plain_site_and_a_folder_that_is_not_a_clone(tmp_path: Path):
    plain, enc, repo = tmp_path / "plain", tmp_path / "enc", tmp_path / "repo"
    build(plain)
    build(enc, "a long enough passphrase")
    repo.mkdir()
    with pytest.raises(ValueError, match="not a git clone"):
        sync_to_repo(enc, repo)
    (repo / ".git").mkdir()
    (repo / "old.html").write_text("old")
    with pytest.raises(ValueError, match="not encrypted"):
        sync_to_repo(plain, repo)
    assert (repo / "old.html").exists()  # refused before touching anything
    n = sync_to_repo(enc, repo)
    assert not (repo / "old.html").exists() and (repo / ".nojekyll").exists()
    assert (repo / ".git").is_dir() and n == len(
        [f for f in repo.rglob("*") if f.is_file() and ".git" not in f.parts]
    )
    assert accords_site.SHELL[0] in {p.name for p in repo.iterdir()}


def test_report_is_a_page_of_the_site_and_gets_the_keys_of_this_build(tmp_path: Path):
    seen = {}

    def report(salt: bytes, pages: frozenset[str]) -> str:
        seen["salt"], seen["pages"] = salt, pages
        return "<h1>Note</h1>"

    out = tmp_path / "site"
    build(out, report=report)
    salt = bytes.fromhex(json.loads((out / "manifest.json").read_text())["salt"])
    assert seen["salt"] == salt
    assert crypto_site.file_key(salt, "ACCOTEXT1") in seen["pages"]
    assert len(seen["pages"]) == 2
    assert (out / "report.html").exists()
    assert (out / "data" / "report.dat").read_text() == "<h1>Note</h1>"
    assert '"report":true' in (out / "data" / "app.dat").read_text()


def test_site_without_report_has_no_report_page_nor_link(tmp_path: Path):
    out = tmp_path / "site"
    build(out)
    assert not (out / "report.html").exists()
    assert not (out / "data" / "report.dat").exists()
    assert '"report":false' in (out / "data" / "app.dat").read_text()


def test_encrypted_report_is_not_readable_in_the_published_files(tmp_path: Path):
    out = tmp_path / "site"
    build(out, "a long enough passphrase", report=lambda salt, pages: "<h1>Note</h1>")
    blob = (out / "data" / "report.dat").read_bytes()
    assert b"Note" not in blob
    manifest = json.loads((out / "manifest.json").read_text())
    key = crypto_site.derive_key(
        "a long enough passphrase", bytes.fromhex(manifest["salt"]), 1000
    )
    assert crypto_site.decrypt(key, blob) == b"<h1>Note</h1>"
