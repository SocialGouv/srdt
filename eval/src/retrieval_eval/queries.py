"""Build `retrieval/queries.jsonl`: the 18 golden questions plus a sample of real ones.

Only the anonymised text is written to the queries file. The original text goes to
a gitignored audit file so that the anonymisation can be reviewed by hand.
"""

import csv
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from retrieval_eval.sampling import (
    BUCKETS,
    Candidate,
    assign_splits,
    build_candidates,
    clean_question,
    is_near_golden,
    length_bucket,
    pii_flags,
    query_id,
    select,
    theme_of,
)

AUDIT_FIELDS = ["query_id", "original", "anonymised", "changed", "pii_flags"]


@dataclass
class QuerySet:
    queries: list[dict]
    # qid, original, anonymised, pii flags: for the manual review, never committed
    audit: list[dict]
    report: str


def load_golden(path: Path) -> list[str]:
    """Distinct questions of the hand-labelled file, in order of appearance."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    return list(dict.fromkeys(row["question"] for row in rows))


def read_export(path: Path) -> list[dict[str, str]]:
    # `newline=""` and a large field limit: questions span lines and some are huge
    csv.field_size_limit(2**30)
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_query_set(
    rows: list[dict[str, str]],
    golden: list[str],
    anonymise: Callable[[str], str],
    n: int,
    seed: int,
    user_cap: int = 5,
    floor: int = 15,
    dev_size: int = 60,
) -> QuerySet:
    candidates, dropped = build_candidates(rows, golden)
    picked = select(candidates, n, seed, user_cap=user_cap, floor=floor)

    records: list[dict] = []
    for g in golden:
        records.append(
            {
                "query_id": query_id(g),
                "text": g,
                "source": "judge18",
                "idcc": None,
                "length_bucket": length_bucket(g),
                "theme": theme_of(g),
            }
        )
    audit: list[dict] = []
    seen = {r["query_id"] for r in records}
    collisions = 0
    for c in picked:
        text = anonymise(c.text)
        qid = query_id(text)
        if qid in seen:  # two originals that anonymise to the same text
            collisions += 1
            continue
        seen.add(qid)
        records.append(
            {
                "query_id": qid,
                "text": text,
                "source": "prod",
                "idcc": c.idcc,
                "length_bucket": c.bucket,
                "theme": c.theme,
            }
        )
        audit.append(
            {
                "query_id": qid,
                "original": c.text,
                "anonymised": text,
                "changed": text != c.text,
                "pii_flags": " ".join(pii_flags(text)),
            }
        )

    splits = assign_splits(
        {r["query_id"]: r["length_bucket"] for r in records}, seed, dev_size
    )
    for r in records:
        r["split"] = splits[r["query_id"]]
    return QuerySet(
        queries=records,
        audit=audit,
        report=render_report(candidates, picked, records, audit, dropped, collisions),
    )


def _share(counter: Counter[str], key: str) -> str:
    total = sum(counter.values())
    return f"{counter[key]:>4} ({counter[key] / total:>4.0%})" if total else "   -"


def render_report(
    candidates: list[Candidate],
    picked: list[Candidate],
    records: list[dict],
    audit: list[dict],
    dropped: Counter[str],
    collisions: int,
) -> str:
    pop_bucket = Counter(c.bucket for c in candidates)
    sample_bucket = Counter(c.bucket for c in picked)
    pop_theme = Counter(c.theme for c in candidates)
    sample_theme = Counter(c.theme for c in picked)
    per_user = Counter(c.user for c in picked)
    split = Counter((r["split"], r["source"]) for r in records)

    lines = [
        f"Candidates: {len(candidates)}  dropped: {dict(dropped)}",
        f"Sampled: {len(picked)} real questions ({collisions} dropped after "
        f"anonymising as duplicates), {len(records)} queries in total",
        "",
        f"{'length bucket':<26}{'population':>14}{'sample':>14}",
        *(
            f"{b:<26}{_share(pop_bucket, b):>14}{_share(sample_bucket, b):>14}"
            for b in BUCKETS
        ),
        "",
        f"{'theme':<26}{'population':>14}{'sample':>14}",
        *(
            f"{t:<26}{_share(pop_theme, t):>14}{_share(sample_theme, t):>14}"
            for t, _ in pop_theme.most_common()
        ),
        "",
        f"Users: {len(per_user)} distinct, "
        f"at most {max(per_user.values())} questions each",
        f"With idcc: population {sum(c.idcc is not None for c in candidates)}"
        f"/{len(candidates)}, sample {sum(c.idcc is not None for c in picked)}"
        f"/{len(picked)}",
        "Split: "
        + ", ".join(f"{s}/{src}={n}" for (s, src), n in sorted(split.items())),
        f"Anonymisation changed {sum(a['changed'] for a in audit)}/{len(audit)} "
        "questions",
    ]
    flagged = [a for a in audit if a["pii_flags"]]
    lines += ["", f"To review by hand (possible leftover PII): {len(flagged)}"]
    lines += [
        f"  {a['query_id']}  [{a['pii_flags']}]  {a['anonymised'][:90]!r}"
        for a in flagged
    ]
    return "\n".join(lines)


def read_queries(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_questions_with_idcc(
    path: Path, text_key: str = "Question", idcc_key: str = "IDCC"
) -> list[tuple[str, str | None]]:
    """`(question, idcc)` pairs of a JSON list of rows; an empty IDCC becomes None."""
    out = []
    for row in json.loads(path.read_text(encoding="utf-8")):
        idcc = str(row.get(idcc_key) or "").strip()
        if idcc.isdigit():
            idcc = idcc.zfill(4)  # the queries file stores 4-digit strings
        out.append((clean_question(row[text_key]), idcc or None))
    return out


@dataclass
class AppendResult:
    queries: list[dict]
    audit: list[dict]
    skipped: list[str]  # query ids already present
    near_existing: list[str]  # new query ids very close to an existing text


def append_queries(
    existing: list[dict],
    questions: list[tuple[str, str | None]],
    source: str,
    anonymise: Callable[[str], str],
    seed: int,
) -> AppendResult:
    """New query records to append, leaving every existing record (and split) alone.

    The new queries get a dev share equal to the existing one, drawn among the new
    queries only: re-running `build_query_set` would redraw the whole split.
    """
    seen = {r["query_id"] for r in existing}
    existing_texts = [r["text"] for r in existing]
    records: list[dict] = []
    audit: list[dict] = []
    skipped: list[str] = []
    near: list[str] = []
    for raw, idcc in questions:
        text = anonymise(raw)
        qid = query_id(text)
        if qid in seen:
            skipped.append(qid)
            continue
        seen.add(qid)
        if is_near_golden(text, existing_texts):
            near.append(qid)
        records.append(
            {
                "query_id": qid,
                "text": text,
                "source": source,
                "idcc": idcc,
                "length_bucket": length_bucket(text),
                "theme": theme_of(text),
            }
        )
        audit.append(
            {
                "query_id": qid,
                "original": raw,
                "anonymised": text,
                "changed": text != raw,
                "pii_flags": " ".join(pii_flags(text)),
            }
        )
    dev_share = sum(r["split"] == "dev" for r in existing) / max(len(existing), 1)
    splits = assign_splits(
        {r["query_id"]: r["length_bucket"] for r in records},
        seed,
        round(dev_share * len(records)),
    )
    for r in records:
        r["split"] = splits[r["query_id"]]
    return AppendResult(records, audit, skipped, near)


def append_records(path: Path, records: list[dict]) -> None:
    """Append lines without rewriting (and so without touching) existing ones."""
    with path.open("a", encoding="utf-8") as f:
        f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def append_audit(path: Path, audit: list[dict]) -> None:
    fresh = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_FIELDS)
        if fresh:
            writer.writeheader()
        writer.writerows(audit)


def write_queries(path: Path, records: list[dict], force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(
            f"{path} exists. The dev/test split must stay fixed: pass --force to "
            "rebuild it on purpose."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )


def write_audit(path: Path, audit: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(audit)
