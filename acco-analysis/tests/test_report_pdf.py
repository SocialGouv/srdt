import json
import shutil
from datetime import date

import pytest

from acco_analysis import crypto_site
from acco_analysis.corpus import Agreement
from acco_analysis.report_pdf import (
    COUNTS,
    NARROW,
    NBSP,
    QUOTE_KEYS,
    build_data,
    fr_int,
    fr_pct,
    load_quotes,
    render,
    render_html,
    resolve_quotes,
    ui_links,
)


def test_french_formatting():
    assert fr_int(2399) == f"2{NARROW}399"
    assert fr_int(12) == "12"
    assert fr_pct(0.3532) == f"35{NBSP}%"
    assert fr_pct(0.3532, 1) == f"35,3{NBSP}%"
    assert fr_pct(None) == "–"


def agreement(i, company="ACME SA", signed="2021-05-02"):
    return Agreement(
        id=i,
        title="",
        company=company,
        siret=None,
        sector=None,
        idcc=None,
        nature="ACCORD",
        signed=signed,
    )


def test_resolve_quotes_checks_each_quote_against_its_passage():
    passages = {
        "a-1": {"agreement_id": "a", "text": "Le  Texte   de la\nclause entière."}
    }
    quotes = {"k": ("a-1", "le texte de la clause")}
    resolved = resolve_quotes(passages, {"a": agreement("a")}, quotes)
    assert resolved["k"] == {
        "text": "le texte de la clause",
        "company": "ACME SA",
        "year": "2021",
        "url": "https://www.legifrance.gouv.fr/acco/id/a",
        "ui": None,
    }
    with pytest.raises(ValueError, match="k"):
        resolve_quotes(passages, {"a": agreement("a")}, {"k": ("a-1", "autre chose")})
    with pytest.raises(ValueError, match="k"):
        resolve_quotes(passages, {"a": agreement("a")}, {"k": ("zz-1", "le texte")})


def write_quotes(tmp_path, **override):
    quotes = {k: ["a-1", f"a clause long enough for {k}"] for k in QUOTE_KEYS}
    file = tmp_path / "quotes.json"
    file.write_text(json.dumps(quotes | override))
    return file


def test_load_quotes_reads_every_key(tmp_path):
    quotes = load_quotes(write_quotes(tmp_path))
    assert set(quotes) == set(QUOTE_KEYS)
    assert quotes["stop"] == ("a-1", "a clause long enough for stop")


def test_load_quotes_says_where_the_file_goes_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="quotes.json is missing"):
        load_quotes(tmp_path / "quotes.json")


def test_load_quotes_rejects_missing_or_extra_keys(tmp_path):
    file = write_quotes(tmp_path, extra=["a-1", "a clause long enough"])
    with pytest.raises(ValueError, match="extra"):
        load_quotes(file)
    quotes = json.loads(file.read_text())
    del quotes["extra"], quotes["stop"]
    file.write_text(json.dumps(quotes))
    with pytest.raises(ValueError, match="stop"):
        load_quotes(file)


def test_load_quotes_rejects_a_quote_too_short_to_be_checked(tmp_path):
    # label.verbatim ignores anything under 20 characters
    with pytest.raises(ValueError, match="stop"):
        load_quotes(write_quotes(tmp_path, stop=["a-1", "trop court"]))


def share_of(year, value):
    return {
        "collected": 120 if year < 2026 else 40,
        "items": {
            "families": {
                "telework": {"share_loose": value},
                "prevention": {"share_loose": value / 2},
            }
        },
    }


def sample_metrics():
    dimensions: dict = {}
    for dimension, code in COUNTS.values():
        dimensions.setdefault(dimension, {})[code] = {"strict": 3}
    dimensions["pay"]["unspecified"]["strict"] = 90
    years = [str(y) for y in range(2017, 2027)]
    return {
        "snapshot": "s1",
        "dimensions": dimensions,
        "dataset": {
            "years": years,
            "collected": 2399,
            "with_heat_clause_loose": 2064,
            "with_heat_clause_strict": 2009,
            "agreements_in_a_template": 934,
            "template_share_of_heat": 0.4525,
            "template_groups": 346,
            "template_largest_group_agreements": 67,
        },
        "quantities": {
            "temperature_c": {"agreements": 229, "thresholds": {"30": 114, "28": 38}}
        },
        # telework peaks in 2026 (partial) and in 2018 (33 agreements): neither counts
        "by_year": {
            y: share_of(int(y), {"2026": 0.9, "2018": 0.8, "2022": 0.5}.get(y, 0.2))
            | ({"collected": 33} if y == "2018" else {})
            for y in years
        },
    }


FACTS = {
    "with_heat": 100,
    "specific": 60,
    "generic_only": 40,
    "specific_schedule": 30,
    "generic_telework": 20,
    "generic_same_day": 10,
    "sec_c": 60,
    "sec_n": 20,
    "sec_o": 15,
    "sec_h": 15,
    "sec_f": 10,
    "sec_c_dedicated": 48,
    "sec_h_dedicated": 14,
    "sec_f_dedicated": 8,
    "sec_o_dedicated": 4,
    "sec_o_telework": 13,
    "prime_total": 10,
    "prime_c": 6,
    "rest_total": 8,
    "rest_c": 4,
    "same_day_total": 12,
    "collective_total": 7,
    "land": 15,
    "land_idcc": 14,
    "land_template": 12,
    "land_same_day": 8,
    "land_collective": 6,
    "no_ape": 2,
    "decree": 17,
    "withdrawal": 1,
    "collective_stoppage": 71,
    "collective_stoppage_recovery": 70,
    "telework": 50,
    "telework_exceptional": 45,
}


def sample_quotes():
    return {
        k: {
            "text": f"clause {k}",
            "company": "ACME SA",
            "year": "2021",
            "url": "u",
            "ui": None,
        }
        for k in QUOTE_KEYS
    }


def test_build_data_formats_the_figures_the_prose_cites():
    data = build_data(sample_metrics(), FACTS, sample_quotes(), today=date(2026, 11, 2))
    f = data["f"]
    assert data["generated"] == "2026-11-02" and data["snapshot"] == "s1"
    assert f["specific_share"] == f"60{NBSP}%"
    assert f["generic"] == "40"
    assert f["collected"] == f"2{NARROW}399"
    assert f["pay_unspecified_share"] == f"90{NBSP}%"  # 90 of the 100 agreements read
    assert f["telework_exceptional_share"] == f"90{NBSP}%"
    assert f["withdrawal"] == "1 accord"
    assert f["threshold_30"] == "114"
    assert set(COUNTS) <= set(f)


def test_withdrawal_is_plural_above_one():
    data = build_data(sample_metrics(), FACTS | {"withdrawal": 2}, sample_quotes())
    assert data["f"]["withdrawal"] == "2 accords"


def test_telework_peak_ignores_the_partial_year_and_small_years():
    f = build_data(sample_metrics(), FACTS, sample_quotes())["f"]
    assert f["telework_peak_year"] == "2022"
    assert f["telework_peak"] == f"50{NBSP}%"
    assert f["last_year"] == "2025" and f["partial_year"] == "2026"
    assert f["prevention_partial"] == f"45{NBSP}%"


def test_data_is_json_serialisable():
    json.dumps(build_data(sample_metrics(), FACTS, sample_quotes()))


def test_ui_links_need_an_address_and_a_published_build(tmp_path):
    assert ui_links(tmp_path, "https://x.example/site") is None  # no build
    (tmp_path / "data").mkdir()
    (tmp_path / "manifest.json").write_text(json.dumps({"salt": "00ff"}))
    assert ui_links(tmp_path, "") is None  # no address


def test_quotes_link_to_the_agreement_page_at_the_section(tmp_path):
    salt = bytes.fromhex("00ff")
    key = crypto_site.file_key(salt, "a")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / f"{key}.dat").write_bytes(b"x")
    (tmp_path / "manifest.json").write_text(json.dumps({"salt": salt.hex()}))
    ui = ui_links(tmp_path, "https://x.example/site/")
    assert ui and ui.home == "https://x.example/site/"
    passages = {
        "a-12-3": {"agreement_id": "a", "text": "le texte de la clause entière"},
        "b-1": {"agreement_id": "b", "text": "le texte de la clause entière"},
    }
    agreements = {"a": agreement("a"), "b": agreement("b")}
    quotes = {
        "k": ("a-12-3", "le texte de la clause"),
        "m": ("b-1", "le texte de la clause"),
    }
    resolved = resolve_quotes(passages, agreements, quotes, ui=ui)
    assert resolved["k"]["ui"] == f"https://x.example/site/accord.html?k={key}#s12"
    assert resolved["m"]["ui"] is None  # that agreement has no page in the build
    assert resolve_quotes(passages, agreements, quotes)["k"]["ui"] is None  # no UI


@pytest.mark.skipif(shutil.which("typst") is None, reason="typst not installed")
@pytest.mark.parametrize("home", [None, "https://x.example/site/"])
def test_template_compiles_with_and_without_ui_links(tmp_path, home):
    # typst fails on a field the template reads and the data lacks, or on a name the
    # style does not export
    quotes = sample_quotes()
    if home:
        quotes = {k: q | {"ui": f"{home}accord.html?k=0#s1"} for k, q in quotes.items()}
    data = build_data(sample_metrics(), FACTS, quotes, ui_home=home)
    pdf = tmp_path / "report.pdf"
    pages = render(data, tmp_path / "work", pdf)
    assert pdf.read_bytes().startswith(b"%PDF")
    assert 1 <= pages <= 12


@pytest.mark.skipif(shutil.which("typst") is None, reason="typst not installed")
def test_web_report_is_semantic_html_with_relative_links(tmp_path):
    # Typst's HTML export is experimental: this fails first if a new Typst changes it
    quotes = {
        k: q | {"ui": "accord.html?k=0123456789abcdef#s1"}
        for k, q in sample_quotes().items()
    }
    html = render_html(build_data(sample_metrics(), FACTS, quotes), tmp_path / "web")
    assert "<html" not in html and "<body" not in html  # the inner HTML only
    assert html.count("<h1>") == 1 and "<h2" in html
    assert 'role="doc-toc"' in html
    assert html.count('<figure class="quote">') == len(QUOTE_KEYS)
    assert 'href="accord.html?k=0123456789abcdef#s1"' in html
    assert '<span class="n">' in html
