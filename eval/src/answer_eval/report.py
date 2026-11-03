"""Comparison of the generators: judge verdicts, refusals, cost, and every answer
side by side with the sources it was given."""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

from answer_eval.citations import CitationCheck
from answer_eval.contexts import Context
from answer_eval.generate import Answer
from answer_eval.labelling import HumanLabel, QuestionLabel
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


def _yes_no(value: bool) -> str:
    return "Oui" if value else "Non"


def _pct(values: list[bool]) -> str:
    if not values:
        return "-"
    return f"{100 * sum(values) / len(values):.0f}% ({len(values)})"


def _count(values: list[bool]) -> str:
    return f"{sum(values)}/{len(values)}" if values else "-"


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
    human: dict[str, dict[str, HumanLabel]] | None = None,
    questions: dict[str, dict[str, QuestionLabel]] | None = None,
    citations: dict[str, CitationCheck] | None = None,
) -> tuple[str, str, list[dict[str, object]]]:
    """(summary markdown, answers markdown, per-answer rows for the CSV).
    `questions`: the human "sources suffisantes" labels, {annotator: {query_id:
    label}}; `citations`: the mechanical citation check, {item_id: check}."""
    generators = sorted({a.base for a in answers})
    judges = sorted({p.judge for p in predictions})
    verdicts = _verdicts(predictions)
    human = human or {}
    questions = questions or {}
    citations = citations or {}
    by_key = {(a.base, a.query_id): a for a in answers}
    substituted = sorted(
        (a.generator, a.query_id) for a in answers if a.generator != a.base
    )
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
                "generated_as": answer.generator,
                "status": answer.status,
                "refusal": REFUSAL in text,
                "cc_refusal": CC_REFUSAL in text,
                "finish_reason": answer.finish_reason or "",
                "latency_s": answer.latency_s,
                "prompt_tokens": answer.prompt_tokens,
                "completion_tokens": answer.completion_tokens,
            }
            if check := citations.get(answer.item_id):
                base |= {
                    "quotes": check.quotes,
                    "quotes_verbatim": check.verbatim,
                    "links": check.links,
                    "links_not_in_prompt": " ".join(check.unknown_links),
                }
            for annotator, by_item in human.items():
                label = by_item.get(answer.item_id)
                for c in CRITERIA:
                    base[f"human:{annotator}:{c.value}"] = (
                        label.labels.get(c.value) if label else None
                    )
            for annotator, by_query in questions.items():
                question = by_query.get(context.query_id)
                base[f"human:{annotator}:sources_suffisantes"] = (
                    question.sources_suffisantes if question else None
                )
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
        own = [a for a in answers if a.base == generator]
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

    if substituted:
        parts += [
            "",
            "Answers generated with another setting, replacing the model's own "
            "answer (see generators.toml): "
            + ", ".join(f"`{g}` on {q}" for g, q in substituted)
            + ".",
        ]

    if citations:
        parts += _citations_section(answers, generators, citations)

    for annotator, by_item in human.items():
        parts += ["", f"## Human {annotator}: share of « Oui » (n)", ""]
        human_rows = []
        for generator in generators:
            labelled = [
                by_item[a.item_id].labels
                for a in answers
                if a.base == generator and a.item_id in by_item
            ]
            cells = [generator]
            for criterion in CRITERIA:
                cells.append(_pct([v[criterion.value] for v in labelled]))
            cells.append(_pct([all(v[c.value] for c in CRITERIA) for v in labelled]))
            human_rows.append(cells)
        parts.append(
            _table(
                ["generator", *(SHORT[c.value] for c in CRITERIA), "all three"],
                human_rows,
            )
        )

    if questions:
        parts += _sources_section(contexts, answers, generators, questions)

    for judge in judges:
        parts += ["", f"## Judge {judge}: share of « Oui » (n)", ""]
        judge_rows = []
        for generator in generators:
            labels = [
                verdicts.get((judge, a.item_id), {})
                for a in answers
                if a.base == generator and a.status == "ok"
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
        for annotator, by_query in questions.items():
            question = by_query.get(context.query_id)
            if question:
                sections.append(
                    f"- sources suffisantes ({annotator}): "
                    + _yes_no(question.sources_suffisantes)
                    + (f" — « {question.comment} »" if question.comment else "")
                )
        sections.append("")
        for generator in generators:
            answer = by_key.get((generator, context.query_id))
            if answer is None:
                continue
            marks = []
            for annotator, by_item in human.items():
                label = by_item.get(answer.item_id)
                if label:
                    marks.append(
                        f"{annotator}: "
                        + ", ".join(
                            f"{SHORT[c.value]} {_yes_no(label.labels[c.value])}"
                            for c in CRITERIA
                        )
                        + (f" — « {label.comment} »" if label.comment else "")
                    )
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


def _citations_section(
    answers: list[Answer], generators: list[str], citations: dict[str, CitationCheck]
) -> list[str]:
    rows = []
    for generator in generators:
        checks = [
            citations[a.item_id]
            for a in answers
            if a.base == generator and a.item_id in citations
        ]
        quotes = sum(c.quotes for c in checks)
        verbatim = sum(c.verbatim for c in checks)
        rows.append(
            [
                generator,
                str(len(checks)),
                str(quotes),
                f"{verbatim} ({verbatim / quotes:.0%})" if quotes else "-",
                str(sum(c.quotes == 0 for c in checks)),
                str(sum(c.links for c in checks)),
                str(sum(len(c.unknown_links) for c in checks)),
                str(sum(bool(c.unknown_links) for c in checks)),
            ]
        )
    return [
        "",
        "## Citations (mechanical check, no LLM)",
        "",
        'The prompt requires `> *"verbatim passage"* — [title](url)` quotes and '
        "forbids URLs it did not give. Verbatim ignores case, spaces and "
        'punctuation; a link "not in prompt" may still be a real page (e.g. a '
        "Légifrance article URL built from its LEGIARTI id).",
        "",
        _table(
            [
                "generator",
                "answers",
                "quotes",
                "verbatim",
                "answers without quote",
                "links",
                "links not in prompt",
                "answers with such links",
            ],
            rows,
        ),
    ]


def _sources_section(
    contexts: list[Context],
    answers: list[Answer],
    generators: list[str],
    questions: dict[str, dict[str, QuestionLabel]],
) -> list[str]:
    """Share of questions whose sources suffice, per annotator, and the refusals of
    each generator on the questions with and without sufficient sources: a refusal
    where the sources were enough is the model's failure, not the retrieval's."""
    idcc = {c.query_id for c in contexts if c.idcc}
    parts = [
        "",
        "## Human: sources sufficient to answer? (per question)",
        "",
        _table(
            ["annotator", "share « Oui » (n)"],
            [
                [
                    annotator,
                    _pct([q.sources_suffisantes for q in by_query.values()]),
                ]
                for annotator, by_query in questions.items()
            ],
        ),
    ]
    for annotator, by_query in questions.items():
        rows = []
        for generator in generators:
            cells = [generator]
            for marker, scope in ((CC_REFUSAL, idcc), (REFUSAL, None)):
                for sufficient in (True, False):
                    cells.append(
                        _count(
                            [
                                marker in (a.answer or "")
                                for a in answers
                                if a.base == generator
                                and a.status == "ok"
                                and a.query_id in by_query
                                and by_query[a.query_id].sources_suffisantes
                                is sufficient
                                and (scope is None or a.query_id in scope)
                            ]
                        )
                    )
            rows.append(cells)
        parts += [
            "",
            f"### {annotator}: refusals by sources label (refusals/answers)",
            "",
            _table(
                [
                    "generator",
                    "CC refusals, sources Oui",
                    "CC refusals, sources Non",
                    "refusals, sources Oui",
                    "refusals, sources Non",
                ],
                rows,
            ),
            "",
            "CC refusals are counted on the questions with an IDCC.",
        ]
    return parts


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
