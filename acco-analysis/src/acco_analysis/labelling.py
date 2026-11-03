"""Hand-labelled sample of the relevance filter: build it, then score the filter."""

import csv
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from acco_analysis.relevance import KEPT, LABELS, excerpt

COLUMNS = [
    "id",
    "order",
    "human_label",
    "note",
    "llm_label",
    "check_label",
    "list_like",
    "heading",
    "excerpt",
    "url",
]
SHARE = {"specific": 0.4, "generic": 0.3, "mention": 0.3}
# what the page stores for a passage the labeller could not decide
UNSURE = "unsure"

# a line ending with a page number ("Article 4 ... 12", "p. 6")
_PAGE = re.compile(r"(\t|\.{2,}|\s{2,})\s*(p\.?\s*)?\d{1,3}\s*$")
_VERB = re.compile(
    r"\b(est|sont|sera|seront|peut|peuvent|doit|doivent|pourra|pourront|prévoit|"
    r"prévu|bénéficie|bénéficient|accord[ée]e?s?|met|mettent|applique|appliquent)\b"
)
SHORT_LINE = 90


def looks_like_list(text: str) -> bool:
    """A table of contents, an agenda or a list of items: mostly short lines without
    a verb, or lines that end with a page number. A rough shape test, not a label."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return False
    if sum(bool(_PAGE.search(line)) for line in lines) / len(lines) >= 0.3:
        return True
    short = sum(len(line) < SHORT_LINE for line in lines) / len(lines)
    verbs = sum(bool(_VERB.search(line)) for line in lines) / len(lines)
    return len(lines) >= 3 and short >= 0.7 and verbs <= 0.25


def queue_order(rows: list[dict[str, str]], seed: int = 1) -> list[dict[str, str]]:
    """The rows in the order they should be labelled, with an `order` column (1...).

    Any prefix is balanced, so stopping after 40 still leaves a usable sample: the
    three labels follow SHARE, and inside each label the kinds of rows (the two models
    agree or not, list-like or not) take turns, the rarest kind first."""
    rng = random.Random(seed)
    queues: dict[str, list[list[dict[str, str]]]] = {}
    # sorted: the queue does not depend on the order the rows come in, so running
    # `queue` again after labelling has started does not move anything
    rows = sorted(rows, key=lambda r: r["id"])
    for label in SHARE:
        kinds: dict[tuple[bool, bool], list[dict[str, str]]] = {}
        for row in rows:
            if row["llm_label"] == label:
                key = (row["llm_label"] != row["check_label"], row["list_like"] == "1")
                kinds.setdefault(key, []).append(row)
        for kind in kinds.values():
            rng.shuffle(kind)
        queues[label] = sorted(kinds.values(), key=len)

    turn = dict.fromkeys(SHARE, 0)
    given = dict.fromkeys(SHARE, 0)
    ordered: list[dict[str, str]] = []
    while len(ordered) < len(rows):
        live = [label for label in SHARE if any(queues[label])]
        # the label furthest below its share goes next
        label = min(live, key=lambda x: (given[x] / SHARE[x], x))
        rows_of = queues[label]
        while not rows_of[turn[label] % len(rows_of)]:
            turn[label] += 1
        ordered.append(rows_of[turn[label] % len(rows_of)].pop())
        turn[label] += 1
        given[label] += 1
    return [{**row, "order": str(n)} for n, row in enumerate(ordered, 1)]


def make_sample(
    passages: list[dict[str, Any]],
    relevance: dict[str, dict[str, Any]],
    size: int = 100,
    disagreements: int = 25,
    seed: int = 1,
) -> list[dict[str, str]]:
    """`size` passages: the models' disagreements first (where a human is most useful),
    then the rest spread over the labels."""
    rng = random.Random(seed)
    by_id = {p["id"]: p for p in passages}
    ids = sorted(by_id)
    rng.shuffle(ids)
    chosen = [i for i in ids if relevance[i].get("agree") is False][:disagreements]
    for label, share in SHARE.items():
        wanted = round(size * share)
        pool = [i for i in ids if relevance[i]["label"] == label and i not in chosen]
        have = sum(relevance[i]["label"] == label for i in chosen)
        chosen += pool[: max(0, wanted - have)]
    rows = []
    for i in chosen[:size]:
        p = by_id[i]
        rows.append(
            {
                "id": i,
                "human_label": "",
                "llm_label": relevance[i]["label"],
                "check_label": relevance[i].get("check_label", ""),
                "list_like": "1" if looks_like_list(p["text"]) else "0",
                "heading": p["heading"],
                "excerpt": excerpt(p["text"], 900),
                "url": f"https://www.legifrance.gouv.fr/acco/id/{p['agreement_id']}",
            }
        )
    return queue_order(rows, seed)


def write_csv(file: Path, rows: list[dict[str, str]]) -> None:
    with open(file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(file: Path) -> list[dict[str, str]]:
    with open(file, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _scores(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """pairs: (human, predicted)."""
    kept = [(h in KEPT, p in KEPT) for h, p in pairs]
    tp = sum(h and p for h, p in kept)
    predicted = sum(p for _, p in kept)
    actual = sum(h for h, _ in kept)
    return {
        "n": len(pairs),
        "accuracy_3_labels": round(sum(h == p for h, p in pairs) / len(pairs), 3),
        "kept_precision": round(tp / predicted, 3) if predicted else None,
        "kept_recall": round(tp / actual, 3) if actual else None,
        "confusion": {f"{h}->{p}": n for (h, p), n in sorted(Counter(pairs).items())},
    }


def evaluate(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Precision and recall of "kept" (specific or generic) against the human labels,
    for the main model and for the check model, and apart for list-like rows."""
    done = [r for r in rows if r["human_label"].strip() in LABELS]
    if not done:
        raise ValueError("no row has a human_label (specific, generic or mention)")

    def scores(subset: list[dict[str, str]]) -> dict[str, Any]:
        result = {
            "main": _scores(
                [(r["human_label"].strip(), r["llm_label"]) for r in subset]
            )
        }
        checked = [r for r in subset if r["check_label"] in LABELS]
        if checked:
            result["check"] = _scores(
                [(r["human_label"].strip(), r["check_label"]) for r in checked]
            )
        return result

    report: dict[str, Any] = {
        "labelled": len(done),
        "of": len(rows),
        "unsure": sum(r.get("human_label", "").strip() == UNSURE for r in rows),
        **scores(done),
    }
    for name, flag in (("list_like", "1"), ("prose", "0")):
        subset = [r for r in done if r.get("list_like") == flag]
        if subset:
            report[name] = {"labelled": len(subset), **scores(subset)}
    return report


def import_labels(
    rows: list[dict[str, str]], labels: list[dict[str, str]]
) -> list[dict[str, str]]:
    """The rows with `human_label` and `note` filled from `labels`, a list of
    {"id", "label", "note"} read back from the labelling page. An id that is not in
    the sample, or a label that is not one of LABELS or "unsure", is an error: the
    page and the sample must be the same."""
    known = {r["id"] for r in rows}
    by_id: dict[str, dict[str, str]] = {}
    for item in labels:
        if item["id"] not in known:
            raise ValueError(f"unknown passage {item['id']!r}: not in the sample")
        if item["label"] not in (*LABELS, UNSURE):
            raise ValueError(f"{item['id']}: unknown label {item['label']!r}")
        by_id[item["id"]] = item
    return [
        {
            **r,
            "human_label": by_id[r["id"]]["label"] if r["id"] in by_id else "",
            "note": by_id[r["id"]].get("note", "") if r["id"] in by_id else "",
        }
        for r in rows
    ]
