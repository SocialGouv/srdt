"""Stage 12: the French analysis note on the heat clauses, written with Typst.

The note is prose, written from a reading of the clauses (`report.typ`). Python supplies
what it cites: the figures, formatted French-style (Typst does not insert the spacing
and decimal comma), so a number in the text cannot drift from the JSON; and a few
clauses quoted word for word, each checked against the extract it comes from.
"""

import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from acco_analysis import crypto_site
from acco_analysis.corpus import Agreement
from acco_analysis.label import verbatim

TEMPLATE = Path(__file__).with_name("report.typ")
STYLE = Path(__file__).with_name("report_style.typ")
STYLE_WEB = Path(__file__).with_name("report_style_web.typ")
NARROW = " "  # thousands separator
NBSP = " "
PEAK_MIN_COLLECTED = 100  # years with fewer agreements are too noisy for a maximum

# template name -> (dimension, code) of metrics.json, strict reading (both models agree)
COUNTS: dict[str, tuple[str, str]] = {
    "schedule_shift": ("measures", "schedule_shift"),
    "summer_hours": ("measures", "summer_hours"),
    "water": ("measures", "water"),
    "cooling": ("measures", "cooling"),
    "extra_breaks": ("measures", "extra_breaks"),
    "protective_gear": ("measures", "protective_gear"),
    "prevention_info": ("measures", "prevention_info"),
    "risk_assessment": ("measures", "risk_assessment"),
    "prime": ("measures", "prime"),
    "same_day_change": ("measures", "same_day_change"),
    "rest_derogation": ("measures", "rest_derogation"),
    "collective_stoppage": ("measures", "collective_stoppage"),
    "production_stop": ("measures", "production_stop"),
    "health_follow_up": ("measures", "health_follow_up"),
    "canicule_unqualified": ("triggers", "canicule_unqualified"),
    "temperature_threshold": ("triggers", "temperature_threshold"),
    "fixed_period": ("triggers", "fixed_period"),
    "vigilance_yellow": ("triggers", "vigilance_yellow"),
    "vigilance_orange": ("triggers", "vigilance_orange"),
    "vigilance_red": ("triggers", "vigilance_red"),
    "employer_decision": ("triggers", "employer_decision"),
    "init_employer": ("initiative", "employer"),
    "init_employee": ("initiative", "employee"),
    "init_reps": ("initiative", "agreed_with_reps"),
    "init_unspecified": ("initiative", "unspecified"),
    "init_disagree": ("initiative", "models_disagree"),
    "faculty": ("strength", "permission"),
    "obligation": ("strength", "obligation"),
    "principle": ("strength", "principle"),
    "strength_disagree": ("strength", "models_disagree"),
    "pay_unspecified": ("pay", "unspecified"),
    "pay_unpaid_recovery": ("pay", "recovered_unpaid"),
    "pay_extra": ("pay", "extra_pay"),
    "pay_maintained": ("pay", "maintained"),
    "pay_none": ("pay", "none_explicit"),
    "scope_unspecified": ("scope", "unspecified"),
    "scope_vulnerable": ("scope", "vulnerable"),
    "proc_cse": ("procedure", "reps_consulted"),
    "proc_consent": ("procedure", "employee_consent"),
}

# The clauses the template quotes (`#q("key")`). Their text is read from out/quotes.json
# ({key: [passage id, quote]}): quotes of agreements stay out of the repo.
QUOTE_KEYS = (
    "hours_canicule",
    "plan_duerp",
    "decree",
    "accuweather",
    "same_day",
    "recovery",
    "rest12",
    "telework",
    "tiers",
    "stop",
    "discretion",
)
QUOTES_FILE = "quotes.json"
QUOTE_MIN = 20  # label.verbatim ignores anything shorter


def fr_int(n: int) -> str:
    return f"{n:,}".replace(",", NARROW)


def fr_pct(x: float | None, digits: int = 0) -> str:
    if x is None:
        return "–"
    return f"{x * 100:.{digits}f}".replace(".", ",") + f"{NBSP}%"


@dataclass(frozen=True)
class UiLinks:
    """Where the published UI keeps the agreements: its address and the salt that names
    the agreement files (`crypto_site.file_key`), so a link needs the build that was
    published."""

    home: str
    salt: bytes
    pages: frozenset[str]  # file keys of the agreement pages that exist

    def agreement(self, agreement_id: str, section: int) -> str | None:
        key = crypto_site.file_key(self.salt, agreement_id)
        if key not in self.pages:
            return None
        return f"{self.home}accord.html?k={key}#s{section}"


def ui_links(site_dir: Path, base_url: str) -> UiLinks | None:
    """The links to the UI, from the encrypted build in `site_dir` (the one published:
    its manifest holds the salt), or None without an address or a build."""
    manifest = site_dir / "manifest.json"
    if not base_url or not manifest.exists():
        return None
    salt = bytes.fromhex(json.loads(manifest.read_text())["salt"])
    pages = frozenset(f.stem for f in (site_dir / "data").glob("*.dat"))
    return UiLinks(base_url.rstrip("/") + "/", salt, pages)


def load_quotes(file: Path) -> dict[str, tuple[str, str]]:
    """The quotes of `file`, which must hold exactly `QUOTE_KEYS`, each as
    [passage id, quote] with a quote long enough to be checked."""
    if not file.exists():
        raise FileNotFoundError(
            f"{file} is missing: it holds the quoted clauses ({', '.join(QUOTE_KEYS)}) "
            "as {key: [passage id, quote]}, and stays out of the repo"
        )
    raw = json.loads(file.read_text())
    if set(raw) != set(QUOTE_KEYS):
        diff = sorted(set(raw) ^ set(QUOTE_KEYS))
        raise ValueError(f"{file}: keys differ from QUOTE_KEYS: {', '.join(diff)}")
    short = [k for k, (_, text) in raw.items() if len(text) < QUOTE_MIN]
    if short:
        raise ValueError(f"{file}: quotes under {QUOTE_MIN} characters: {short}")
    return {k: (passage_id, text) for k, (passage_id, text) in raw.items()}


def resolve_quotes(
    passages: Mapping[str, Mapping[str, Any]],
    agreements: Mapping[str, Agreement],
    quotes: Mapping[str, tuple[str, str]],
    ui: UiLinks | None = None,
) -> dict[str, dict[str, str | None]]:
    """The quotes with their source and, given the UI, the link to the agreement page at
    the section of the quote; each quote is checked word for word against its passage.
    Raises if one is no longer in the extracts (a changed extraction or snapshot)."""
    missing = [
        key
        for key, (passage_id, text) in quotes.items()
        if passage_id not in passages
        or not verbatim(text, passages[passage_id]["text"])
    ]
    if missing:
        raise ValueError(f"quotes not found in their passage: {', '.join(missing)}")
    resolved = {}
    for key, (passage_id, text) in quotes.items():
        agreement = agreements[passages[passage_id]["agreement_id"]]
        section = int(passage_id.split("-")[1])  # {agreement}-{section}[-{n}]
        resolved[key] = {
            "text": text,
            "company": agreement.company,
            "year": (agreement.signed or "")[:4],
            "url": agreement.url,
            "ui": ui.agreement(agreement.id, section) if ui else None,
        }
    return resolved


def _count(metrics: Mapping[str, Any], dimension: str, code: str) -> int:
    return metrics["dimensions"][dimension][code]["strict"]


def _share_of_year(metrics: Mapping[str, Any], year: str, family: str) -> float:
    return metrics["by_year"][year]["items"]["families"][family]["share_loose"]


def _trend(metrics: Mapping[str, Any]) -> dict[str, str]:
    """Where telework peaks (a year with enough agreements, not the partial one) and
    how it and prevention look in the last full year and the partial one."""
    years = metrics["dataset"]["years"]
    partial, last = years[-1], years[-2]
    full = [
        y
        for y in years[:-1]
        if metrics["by_year"][y]["collected"] >= PEAK_MIN_COLLECTED
    ]
    peak = max(full, key=lambda y: _share_of_year(metrics, y, "telework"))
    return {
        "telework_peak_year": peak,
        "telework_peak": fr_pct(_share_of_year(metrics, peak, "telework")),
        "telework_last": fr_pct(_share_of_year(metrics, last, "telework")),
        "prevention_last": fr_pct(_share_of_year(metrics, last, "prevention")),
        "last_year": last,
        "partial_year": partial,
        "prevention_partial": fr_pct(_share_of_year(metrics, partial, "prevention")),
    }


def _sectors(facts: Mapping[str, int]) -> dict[str, str]:
    """The figures of the section on sectors, formatted (shares of the agreements with a
    heat clause, of a sector, or of all the agreements with a measure)."""
    heat = facts["with_heat"]
    share = fr_pct
    return {
        "sec_c": fr_int(facts["sec_c"]),
        "sec_c_share": share(facts["sec_c"] / heat),
        "sec_n_share": share(facts["sec_n"] / heat),
        "sec_o_share": share(facts["sec_o"] / heat),
        "sec_h_share": share(facts["sec_h"] / heat),
        "sec_f_share": share(facts["sec_f"] / heat),
        "sec_c_dedicated": share(facts["sec_c_dedicated"] / facts["sec_c"]),
        "sec_h_dedicated": share(facts["sec_h_dedicated"] / facts["sec_h"]),
        "sec_f_dedicated": share(facts["sec_f_dedicated"] / facts["sec_f"]),
        "sec_o_dedicated": share(facts["sec_o_dedicated"] / facts["sec_o"]),
        "sec_o_telework": share(facts["sec_o_telework"] / facts["sec_o"]),
        "prime_industry_share": share(facts["prime_c"] / facts["prime_total"]),
        "rest_industry_share": share(facts["rest_c"] / facts["rest_total"]),
        "land": fr_int(facts["land"]),
        "land_idcc": fr_int(facts["land_idcc"]),
        "land_template": fr_int(facts["land_template"]),
        "land_same_day": fr_int(facts["land_same_day"]),
        "land_collective": fr_int(facts["land_collective"]),
        "land_same_day_share": share(facts["land_same_day"] / facts["same_day_total"]),
        "collective_total": fr_int(facts["collective_total"]),
        "other_collective": fr_int(
            facts["collective_total"] - facts["land_collective"]
        ),
        "other_same_day": fr_int(facts["same_day_total"] - facts["land_same_day"]),
        "no_ape": fr_int(facts["no_ape"]),
    }


def build_data(
    metrics: Mapping[str, Any],
    facts: Mapping[str, int],
    quotes: Mapping[str, Mapping[str, str | None]],
    today: date | None = None,
    ui_home: str | None = None,
) -> dict[str, Any]:
    d = metrics["dataset"]
    temperatures = metrics["quantities"]["temperature_c"]
    with_heat = facts["with_heat"]
    f: dict[str, str] = {
        name: fr_int(_count(metrics, dim, code)) for name, (dim, code) in COUNTS.items()
    }
    f |= {
        "collected": fr_int(d["collected"]),
        "years": f"{d['years'][0]} à {d['years'][-1]}",
        "heat_loose": fr_int(d["with_heat_clause_loose"]),
        "heat_strict": fr_int(d["with_heat_clause_strict"]),
        "specific": fr_int(facts["specific"]),
        "specific_share": fr_pct(facts["specific"] / with_heat),
        "generic": fr_int(facts["generic_only"]),
        "generic_share": fr_pct(facts["generic_only"] / with_heat),
        "pay_unspecified_share": fr_pct(
            _count(metrics, "pay", "unspecified") / with_heat
        ),
        **_sectors(facts),
        "specific_schedule": fr_int(facts["specific_schedule"]),
        "generic_telework": fr_int(facts["generic_telework"]),
        "generic_same_day": fr_int(facts["generic_same_day"]),
        "decree": fr_int(facts["decree"]),
        "withdrawal": f"{fr_int(facts['withdrawal'])} "
        + ("accords" if facts["withdrawal"] > 1 else "accord"),
        "collective_stoppage_recovery": fr_int(facts["collective_stoppage_recovery"]),
        "telework": fr_int(facts["telework"]),
        "telework_exceptional": fr_int(facts["telework_exceptional"]),
        "telework_exceptional_share": fr_pct(
            facts["telework_exceptional"] / facts["telework"]
        ),
        "template_agreements": fr_int(d["agreements_in_a_template"]),
        "template_share": fr_pct(d["template_share_of_heat"]),
        "template_groups": fr_int(d["template_groups"]),
        "template_largest": fr_int(d["template_largest_group_agreements"]),
        "temperature_agreements": fr_int(temperatures["agreements"]),
        "threshold_30": fr_int(temperatures["thresholds"]["30"]),
        "threshold_28": fr_int(temperatures["thresholds"]["28"]),
    }
    f |= _trend(metrics)
    return {
        "snapshot": metrics["snapshot"],
        "generated": (today or date.today()).isoformat(),
        "f": f,
        "quotes": quotes,
        "ui_home": ui_home,
    }


def typst_binary() -> str:
    found = shutil.which("typst")
    if not found:
        raise RuntimeError("typst not found on PATH (brew install typst)")
    return found


def _run(args: Sequence[str]) -> str:
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f"typst failed:\n{done.stderr.strip()}")
    return done.stdout


def render(
    data: Mapping[str, Any],
    work_dir: Path,
    pdf: Path,
    template: Path = TEMPLATE,
) -> int:
    """Write `data.json`, the template and the style into `work_dir`, compile to `pdf`
    and return the page count."""
    typst = typst_binary()
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    shutil.copy(template, work_dir / TEMPLATE.name)
    shutil.copy(STYLE, work_dir / "style.typ")
    source = str(work_dir / TEMPLATE.name)
    _run([typst, "compile", "--root", str(work_dir), source, str(pdf)])
    pages = _run([typst, "query", "--root", str(work_dir), source, "<pages>"])
    return int(json.loads(pages)[0]["value"])


def render_html(data: Mapping[str, Any], work_dir: Path) -> str:
    """The report as the inner HTML of a page, for the UI: the same `report.typ` with the
    web style, through Typst's HTML export (experimental in Typst, so the tests build it).
    Quote links in `data` should be relative (`UiLinks` with an empty home)."""
    typst = typst_binary()
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    shutil.copy(TEMPLATE, work_dir / TEMPLATE.name)
    shutil.copy(STYLE_WEB, work_dir / "style.typ")
    html_file = work_dir / "report.html"
    source = str(work_dir / TEMPLATE.name)
    _run(
        [typst, "compile", "--features", "html", "--format", "html", "--root"]
        + [str(work_dir), source, str(html_file)]
    )
    body = re.search(r"<body>(.*)</body>", html_file.read_text(), re.DOTALL)
    if not body:
        raise RuntimeError("typst's HTML export has no <body>")
    return body.group(1)
