"""The agreement viewer: out/site/ (plain, local preview) or out/site-enc/ (encrypted,
for GitHub Pages).

Public files: the shell pages and `gate.js` (`pages/`), `manifest.json`. Everything with
content is a data file read by `gate.js`: `data/app.dat` (the nuances page) and one
`data/<key>.dat` per agreement placed in a nuance (its sections, the passages the models
read and the quotes shown). When encrypted, the data files are named by a salted hash of
the agreement id, so the public file list does not say which agreements are in.
"""

import json
import shutil
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ingestion.sources.accords import split_sections

from acco_analysis import crypto_site, site
from acco_analysis.corpus import Agreement
from acco_analysis.label import clean_quote

PAGES = Path(__file__).with_name("pages")
SHELL = ("index.html", "accord.html", "gate.js")
REPORT_SHELL = "report.html"
# (salt, file keys of the agreement pages) -> the report as HTML: its links to agreement
# pages need the keys of this very build
Report = Callable[[bytes, frozenset[str]], str]


def _fold_with_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    """`label.verbatim`'s folding (NFKC, case, spacing), and for every folded character
    the [start, stop) range of the original characters it comes from."""
    folded: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        j = i + 1
        while j < len(text) and unicodedata.combining(text[j]):
            j += 1  # an accent written as its own character stays with its letter
        for char in unicodedata.normalize("NFKC", text[i:j]).casefold():
            if char.isspace():
                if folded and folded[-1] == " ":
                    spans[-1] = (spans[-1][0], j)
                    continue
                char = " "
            folded.append(char)
            spans.append((i, j))
        i = j
    return "".join(folded), spans


def locate(text: str, quote: str) -> tuple[int, int] | None:
    """The [start, stop) span of `text` that `quote` was copied from, or None."""
    wanted = clean_quote(quote)
    if len(wanted) < 20:
        return None
    folded, spans = _fold_with_map(text)
    at = folded.find(wanted)
    if at < 0:
        return None
    return spans[at][0], spans[at + len(wanted) - 1][1]


def line_marks(
    lines: Sequence[str], start: int, stop: int, span: tuple[int, int]
) -> list[list[int]]:
    """`[line, from, to]` pieces of a span of "\\n".join(lines[start:stop])."""
    marks: list[list[int]] = []
    offset = 0
    for k in range(start, stop):
        first, last = max(span[0], offset), min(span[1], offset + len(lines[k]))
        if first < last:
            marks.append([k, first - offset, last - offset])
        offset += len(lines[k]) + 1
    return marks


def memberships(
    flavours: Mapping[str, Any], loose: Mapping[str, Mapping[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Per agreement id: its family badges (the nuance it is placed in, or none for
    "other combinations"), then the families it only has in the loose reading."""
    badges: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, family in flavours["families"].items():
        for f in family["flavours"]:
            nuance = {"id": f["id"], "rank": f["rank"], "name": f.get("name") or ""}
            for a in f["agreements"]:
                badges[a].append(
                    {"family": name, "label": family["label"], "nuance": nuance}
                )
        for a in family["other"]["agreements"]:
            badges[a].append({"family": name, "label": family["label"], "nuance": None})
    labels = {name: fam["label"] for name, fam in flavours["families"].items()}
    for a, rows in badges.items():
        strict = {b["family"] for b in rows}
        for name in loose.get(a, {}).get("families", []):
            if name in labels and name not in strict:
                rows.append(
                    {
                        "family": name,
                        "label": labels[name],
                        "nuance": None,
                        "loose_only": True,
                    }
                )
    return badges


def shown_quotes(flavours: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Per agreement id: the quotes shown on the nuance cards `{id, quote}`."""
    by_agreement: dict[str, list[dict[str, str]]] = defaultdict(list)
    for family in flavours["families"].values():
        for f in family["flavours"]:
            for q in f.get("quotes", []):
                agreement_id = q["url"].rsplit("/", 1)[-1]
                by_agreement[agreement_id].append({"id": q["id"], "quote": q["quote"]})
    return by_agreement


def build_agreement(
    agreement: Agreement,
    passages: Iterable[Mapping[str, Any]],
    badges: list[dict[str, Any]],
    quotes: Iterable[Mapping[str, str]],
    snapshot: str = "",
) -> tuple[dict[str, Any], int, int]:
    """The page data of an agreement and how many of its quotes were (found, missed)."""
    sections = split_sections(agreement.text)
    heat: dict[int, list[list[int]]] = defaultdict(list)
    ranges: dict[str, tuple[int, int, int]] = {}
    for p in passages:
        lines = sections[p["section"]].lines
        start, stop = p.get("start", 0), p.get("stop", 0)
        if stop <= start:  # passages.jsonl written before the line range existed
            start, stop = 0, len(lines)
        heat[p["section"]].append([start, stop])
        ranges[p["id"]] = (p["section"], start, stop)

    marks: dict[int, list[list[int]]] = defaultdict(list)
    found = missed = 0
    for q in quotes:
        where = ranges.get(q["id"])
        if where is None:
            missed += 1
            continue
        n, start, stop = where
        lines = sections[n].lines
        span = locate("\n".join(lines[start:stop]), q["quote"])
        if span is None:
            missed += 1
            continue
        found += 1
        marks[n].extend(line_marks(lines, start, stop, span))

    page = {
        "id": agreement.id,
        "title": agreement.title,
        "company": agreement.company,
        "signed": agreement.signed,
        "idcc": agreement.idcc,
        "sector": agreement.sector,
        "nature": agreement.nature,
        "themes": agreement.themes,
        "unions": agreement.unions,
        "url": agreement.url,
        "snapshot": snapshot,
        "badges": badges,
        "sections": [
            {
                "n": n,
                "h": " > ".join(s.breadcrumb),
                "lines": s.lines,
                "heat": sorted(heat.get(n, [])),
                "marks": sorted(marks.get(n, [])),
            }
            for n, s in enumerate(sections)
            if s.lines or s.breadcrumb
        ],
    }
    return page, found, missed


def _write(path: Path, data: bytes, key: bytes | None) -> None:
    path.write_bytes(crypto_site.encrypt(key, data) if key else data)


def build_site(
    out_dir: Path,
    *,
    password: str | None,
    flavours: dict[str, Any],
    metrics: dict[str, Any],
    agreements: Sequence[Agreement],
    profiles: dict[str, dict[str, dict[str, Any]]],
    passages: Iterable[Mapping[str, Any]],
    iterations: int = crypto_site.ITERATIONS,
    report: Report | None = None,
) -> dict[str, int]:
    """Write the site into `out_dir` (emptied first), encrypted given a password. With
    `report`, the analysis note is a page of the site too (`report.html`)."""
    salt = crypto_site.new_salt()
    key = crypto_site.derive_key(password, salt, iterations) if password else None
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "data").mkdir(parents=True)
    for name in SHELL:
        shutil.copy(PAGES / name, out_dir / name)
    manifest = {
        "version": 1,
        "encrypted": key is not None,
        "kdf": "PBKDF2-SHA256",
        "iterations": iterations,
        "salt": salt.hex(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))

    by_id = {a.id: a for a in agreements}
    by_agreement: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for p in passages:
        by_agreement[p["agreement_id"]].append(p)
    badges = memberships(flavours, profiles["loose"])
    quotes = shown_quotes(flavours)
    found = missed = 0
    placed = site.placed_agreements(flavours)
    pages = frozenset(crypto_site.file_key(salt, a) for a in placed)
    for agreement_id in placed:
        page, f, m = build_agreement(
            by_id[agreement_id],
            by_agreement[agreement_id],
            badges.get(agreement_id, []),
            quotes.get(agreement_id, []),
            flavours.get("snapshot", ""),
        )
        found, missed = found + f, missed + m
        data = json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()
        _write(
            out_dir / "data" / f"{crypto_site.file_key(salt, agreement_id)}.dat",
            data,
            key,
        )

    if report:
        shutil.copy(PAGES / REPORT_SHELL, out_dir / REPORT_SHELL)
        _write(out_dir / "data" / "report.dat", report(salt, pages).encode(), key)
    data = site.build_data(
        flavours, metrics, agreements, profiles, salt, report=report is not None
    )
    _write(out_dir / "data" / "app.dat", site.render(data).encode(), key)
    return {"agreements": len(placed), "quotes_found": found, "quotes_missed": missed}


def sync_to_repo(site_dir: Path, repo: Path) -> int:
    """Replace the content of a git clone with the encrypted site (the `.git` folder
    stays) and return the number of files copied. Pushing is left to the caller."""
    if not (repo / ".git").exists():
        raise ValueError(f"{repo} is not a git clone")
    if not json.loads((site_dir / "manifest.json").read_text())["encrypted"]:
        raise ValueError(f"{site_dir} is not encrypted: refusing to publish it")
    for child in repo.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    shutil.copytree(site_dir, repo, dirs_exist_ok=True)
    (repo / ".nojekyll").write_text("")  # serve the files as they are
    return sum(1 for f in repo.rglob("*") if f.is_file() and ".git" not in f.parts)
