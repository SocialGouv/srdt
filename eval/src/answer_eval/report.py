"""Comparison of the generators: judge verdicts, refusals, cost, and every answer
side by side with the sources it was given."""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

from answer_eval.contexts import Context
from answer_eval.generate import Answer
from judge_eval.data import CRITERIA
from judge_eval.runner import Prediction

# Fixed sentences the instructions impose when the knowledge base does not cover
# the question (LIMITATIONS_TEXT) or the convention collective (CAS 2).
REFUSAL = "Je ne dispose pas d'information sur ce point"
CC_REFUSAL = "Je ne dispose pas d'information spécifique sur votre convention"

SHORT = {
    "correct_en_droit": "correct",
    "suffisant": "suffisant",
    "intelligible": "intelligible",
}


def _verdicts(
    predictions: list[Prediction],
) -> dict[tuple[str, str], dict[str, bool | None]]:
    """{(judge, item_id): {criterion: label}}; None for an unparsable verdict."""
    out: dict[tuple[str, str], dict[str, bool | None]] = defaultdict(dict)
    for p in predictions:
        if p.status == "api_error":
            continue
        out[(p.judge, p.item_id)][p.criterion.value] = p.label
    return out


def _pct(values: list[bool]) -> str:
    if not values:
        return "-"
    return f"{100 * sum(values) / len(values):.0f}% ({len(values)})"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _quote(text: str) -> str:
    return "\n".join("> " + line if line else ">" for line in text.splitlines())


def build_report(
    run_id: str,
    contexts: list[Context],
    answers: list[Answer],
    predictions: list[Prediction],
) -> tuple[str, str, list[dict[str, object]]]:
    """(summary markdown, answers markdown, per-answer rows for the CSV)."""
    generators = sorted({a.generator for a in answers})
    judges = sorted({p.judge for p in predictions})
    verdicts = _verdicts(predictions)
    by_key = {a.key: a for a in answers}
    no_grade2 = {
        c.query_id for c in contexts if not any(f.grade == 2 for f in c.fiches)
    }

    rows: list[dict[str, object]] = []
    for context in contexts:
        for generator in generators:
            answer = by_key.get((generator, context.query_id))
            if answer is None:
                continue
            text = answer.answer or ""
            base = {
                "query_id": context.query_id,
                "idcc": context.idcc or "",
                "no_grade2_fiche": context.query_id in no_grade2,
                "generator": generator,
                "status": answer.status,
                "refusal": REFUSAL in text,
                "cc_refusal": CC_REFUSAL in text,
                "finish_reason": answer.finish_reason or "",
                "latency_s": answer.latency_s,
                "prompt_tokens": answer.prompt_tokens,
                "completion_tokens": answer.completion_tokens,
            }
            for judge in judges or [""]:
                labels = verdicts.get((judge, answer.item_id), {})
                rows.append(
                    {
                        **base,
                        "judge": judge,
                        **{c.value: labels.get(c.value) for c in CRITERIA},
                    }
                )

    # --- Summary
    parts = [
        f"# Answer eval: {run_id}",
        "",
        f"{len(contexts)} questions, {len(generators)} generator(s), "
        f"{len(judges)} judge(s). {len(no_grade2)} question(s) have no fiche "
        "graded 2 (only partial sources).",
        "",
        "## Generation",
        "",
    ]
    gen_rows = []
    for generator in generators:
        own = [a for a in answers if a.generator == generator]
        ok = [a for a in own if a.status == "ok"]
        latencies = [a.latency_s for a in ok if a.latency_s is not None]
        out_tokens = [a.completion_tokens for a in ok if a.completion_tokens]
        gen_rows.append(
            [
                generator,
                f"{len(ok)}/{len(contexts)}",
                str(sum(a.status == "empty" for a in own)),
                str(sum(a.status == "api_error" for a in own)),
                str(sum(a.finish_reason == "length" for a in own)),
                str(sum(REFUSAL in (a.answer or "") for a in ok)),
                str(sum(CC_REFUSAL in (a.answer or "") for a in ok)),
                f"{statistics.median(latencies):.0f}s" if latencies else "-",
                f"{statistics.mean(out_tokens):.0f}" if out_tokens else "-",
            ]
        )
    parts.append(
        _table(
            [
                "generator",
                "answered",
                "empty",
                "API errors",
                "cut (length)",
                "refusals",
                "CC refusals",
                "median latency",
                "mean output tokens",
            ],
            gen_rows,
        )
    )

    for judge in judges:
        parts += ["", f"## Judge {judge}: share of « Oui » (n)", ""]
        judge_rows = []
        for generator in generators:
            labels = [
                verdicts.get((judge, a.item_id), {})
                for a in answers
                if a.generator == generator and a.status == "ok"
            ]
            cells = [generator]
            for criterion in CRITERIA:
                cells.append(
                    _pct(
                        [
                            v[criterion.value]
                            for v in labels
                            if v.get(criterion.value) is not None
                        ]
                    )
                )
            complete = [
                v for v in labels if all(v.get(c.value) is not None for c in CRITERIA)
            ]
            cells.append(_pct([all(v[c.value] for c in CRITERIA) for v in complete]))
            judge_rows.append(cells)
        parts.append(
            _table(
                ["generator", *(SHORT[c.value] for c in CRITERIA), "all three"],
                judge_rows,
            )
        )
    parts += [
        "",
        "Answers not generated (empty, API error) are not judged: compare with the "
        "`answered` column. Unparsable verdicts are left out of the shares.",
        "",
    ]
    summary = "\n".join(parts)

    # --- Answers side by side
    sections = [f"# Answers: {run_id}", ""]
    for number, context in enumerate(contexts, start=1):
        sections += [
            f"## {number}. {context.query_id}"
            + (
                f" (IDCC {context.idcc} {context.idcc_name or ''})"
                if context.idcc
                else ""
            ),
            "",
            _quote(context.text),
            "",
            "**Sources**",
            "",
        ]
        for f in context.fiches:
            sections.append(
                f"- fiche, grade {f.grade}: [{f.metadata.title}]({f.metadata.url})"
            )
        for c in context.code:
            sections.append(
                f"- code du travail: [{c.metadata.title}]({c.metadata.url})"
            )
        for c in context.idcc_chunks:
            sections.append(f"- convention: [{c.metadata.title}]({c.metadata.url})")
        sections.append("")
        for generator in generators:
            answer = by_key.get((generator, context.query_id))
            if answer is None:
                continue
            marks = []
            for judge in judges:
                labels = verdicts.get((judge, answer.item_id), {})
                marks.append(
                    ", ".join(
                        f"{SHORT[c.value]} "
                        + {True: "Oui", False: "Non", None: "?"}[labels.get(c.value)]
                        for c in CRITERIA
                    )
                )
            heading = f"### {generator}"
            if marks:
                heading += " (" + "; ".join(marks) + ")"
            sections += [heading, ""]
            if answer.status == "ok":
                sections.append(answer.answer or "")
            else:
                sections.append(f"*{answer.status}: {answer.error or ''}*")
            sections.append("")
    return summary, "\n".join(sections), rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
