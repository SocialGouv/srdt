"""Hand check of the closed coding: a local page where the passage is coded blind, then
the model's coding is scored against it."""

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from acco_analysis.codebook import DIMENSIONS, families_of
from acco_analysis.relevance import excerpt

PAGE = Path(__file__).with_name("coding_check.html")
EXCERPT_CHARS = 2500


def _codes(coded: dict[str, Any], dimension: str) -> set[str]:
    return {x["code"] if isinstance(x, dict) else x for x in coded[dimension]}


def queue_items(
    rows: list[dict[str, Any]],
    passages: dict[str, dict[str, Any]],
    groups: dict[str, int],
    size: int = 40,
    seed: int = 1,
) -> list[dict[str, Any]]:
    """`size` passages to code by hand, in an order where any prefix is balanced.

    Each group (the old family) gives passages in turn where the two models give
    different measures and where they agree, and the groups take turns, so stopping
    early still leaves a sample that mixes both."""
    rng = random.Random(seed)
    queues: dict[int, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = defaultdict(
        lambda: ([], [])
    )
    for row in sorted(rows, key=lambda r: r["id"]):
        differ = _codes(row["main"], "measures") != _codes(row["check"], "measures")
        queues[groups[row["id"]]][0 if differ else 1].append(row)
    ordered: dict[int, list[dict[str, Any]]] = {}
    for group, (differ, agree) in sorted(queues.items()):
        rng.shuffle(differ)
        rng.shuffle(agree)
        turns: list[dict[str, Any]] = []
        while differ or agree:
            for queue in (differ, agree):
                if queue:
                    turns.append(queue.pop())
        ordered[group] = turns
    picked: list[dict[str, Any]] = []
    while len(picked) < size and any(ordered.values()):
        for turns in ordered.values():
            if turns and len(picked) < size:
                picked.append(turns.pop(0))
    return [
        {
            "id": row["id"],
            "order": n,
            "heading": passages[row["id"]]["heading"],
            "text": excerpt(passages[row["id"]]["text"], EXCERPT_CHARS),
            "url": f"https://www.legifrance.gouv.fr/acco/id/{row['agreement_id']}",
        }
        for n, row in enumerate(picked, 1)
    ]


def render_page(items: list[dict[str, Any]]) -> str:
    """The self-contained page: passages and codebook embedded, nothing fetched."""
    data = {
        "items": items,
        "dimensions": [
            {
                "name": d.name,
                "label": d.label,
                "multi": d.multi,
                "values": [
                    {"code": c, "label": label, "definition": definition}
                    for c, (label, definition) in d.values.items()
                ],
            }
            for d in DIMENSIONS
        ],
    }
    # "</script>" inside a passage must not end the script element
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.read_text().replace("__DATA__", blob)


def read_labels(file: Path) -> dict[str, dict[str, Any]]:
    """The labels of the passages the page marked as validated."""
    exported = json.loads(file.read_text())
    return {
        i: exported["labels"][i] for i in exported["done"] if i in exported["labels"]
    }


def _scores(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    return {
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
    }


def evaluate(
    rows: list[dict[str, Any]], labels: dict[str, dict[str, Any]], min_count: int = 3
) -> dict[str, Any]:
    """Each model's coding against the hand coding, on the passages coded by hand.

    Multi-valued dimensions: precision and recall, overall and per code (codes with at
    least `min_count` hand or model uses). Single-valued: accuracy. Families: the share
    of passages whose family set (derived from the measures) is the same."""
    rows = [r for r in rows if r["id"] in labels]
    report: dict[str, Any] = {"passages": len(rows)}
    for model in ("main", "check"):
        out: dict[str, Any] = {}
        for d in DIMENSIONS:
            if d.multi:
                human = {r["id"]: set(labels[r["id"]][d.name]) for r in rows}
                coded = {r["id"]: _codes(r[model], d.name) for r in rows}
                tp = sum(len(human[i] & coded[i]) for i in human)
                fp = sum(len(coded[i] - human[i]) for i in human)
                fn = sum(len(human[i] - coded[i]) for i in human)
                per_code: dict[str, Any] = {}
                for code in d.values:
                    h = sum(code in human[i] for i in human)
                    m = sum(code in coded[i] for i in human)
                    if max(h, m) >= min_count:
                        ctp = sum(code in human[i] and code in coded[i] for i in human)
                        per_code[code] = {
                            "human": h,
                            "model": m,
                            **_scores(ctp, m - ctp, h - ctp),
                        }
                out[d.name] = {**_scores(tp, fp, fn), "codes": per_code}
            else:
                same = sum(r[model][d.name] == labels[r["id"]][d.name] for r in rows)
                out[d.name] = {"accuracy": round(same / len(rows), 3) if rows else None}
        same_family = sum(
            set(r[model]["families"])
            == set(families_of(set(labels[r["id"]]["measures"])))
            for r in rows
        )
        out["families_exact"] = round(same_family / len(rows), 3) if rows else None
        report[model] = out
    report["not_about_heat_by_hand"] = sum(
        not labels[r["id"]]["about_heat"] for r in rows
    )
    return report
