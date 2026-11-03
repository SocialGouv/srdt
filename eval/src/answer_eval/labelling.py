"""Blind human labelling of the generated answers.

`build_page` writes a self-contained HTML page: one screen per question, its answers
shuffled (seeded, per question) and shown as A, B, C, D, each judged Oui/Non on the
judge's three criteria, with the sources the models were given in a folded block.
Each question also gets one Oui/Non label of its own, "sources suffisantes" (were
the sources enough to answer?), with the id `07-Q`: it judges the retrieval, not the
answers. Nothing on the page tells which model wrote an answer: the mapping from a
`label_id` (`07-C`) to the answer lives only in the key file, next to the page.

The page autosaves in the browser and exports a CSV; `import_labels` reads it back
with the key into human labels, and into the `18q_human.json` format so that
`judge-eval run --dataset` can score the LLM judges against this labeller.

`build_data` is the page's content alone: `publish.py` hosts it apart from the page.

Answers are Markdown: they are rendered to HTML here with raw HTML disabled, so
whatever a model wrote is escaped, and the page inserts no other HTML.
"""

import csv
import hashlib
import json
import random
import re
import string
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from pydantic import BaseModel, Field

from answer_eval.contexts import Context
from answer_eval.generate import Answer
from answer_eval.prompt import Chunk, chunk_title
from judge_eval.data import CRITERIA
from retrieval_eval.labelling_ui import _json_for_script

TEMPLATE = Path(__file__).parent / "templates" / "answers_labelling.html"
KEY_FILE = "key.json"
VALUES = ("Oui", "Non")
# The per-question label: its CSV column, and the suffix of its label_id (`07-Q`).
SOURCES_COLUMN = "sources_suffisantes"
QUESTION_SUFFIX = "Q"
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

CRITERIA_LABELS = {
    "correct_en_droit": "Correct en droit",
    "suffisant": "Suffisant",
    "intelligible": "Intelligible",
}

_markdown = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def render_markdown(text: str) -> str:
    """HTML of a model answer. Raw HTML in the text is escaped (`html: False`) and
    markdown-it refuses `javascript:` and similar links."""
    return _markdown.render(text)


def answer_sha256(answer: Answer) -> str:
    return hashlib.sha256((answer.answer or "").encode("utf-8")).hexdigest()


def criterion_definitions(prompts_dir: Path) -> list[dict[str, str]]:
    """The judge's definition of each criterion, written for the LLM ("Réponds
    « Oui » si…") and shown as is to the human, so both judge the same thing."""
    out = []
    for criterion in CRITERIA:
        raw = (prompts_dir / f"{criterion.value}.fr.md").read_text(encoding="utf-8")
        text = _HTML_COMMENT.sub("", raw).strip()
        text = re.sub(r"^#+ .*\n+", "", text)  # the heading, replaced by the label
        out.append(
            {
                "key": criterion.value,
                "label": CRITERIA_LABELS[criterion.value],
                "definition": text,
            }
        )
    return out


def _source(chunk: Chunk) -> dict[str, str]:
    return {
        "title": chunk_title(chunk),
        "url": chunk.metadata.url,
        "text": chunk.content,
    }


def _letters(n: int) -> str:
    return string.ascii_uppercase[:n]


class KeyItem(BaseModel):
    label_id: str
    item_id: str
    generator: str
    query_id: str
    answer_sha256: str


class KeyQuestion(BaseModel):
    label_id: str  # `07-Q`
    query_id: str


class Key(BaseModel):
    dataset_id: str
    run_id: str
    seed: int
    created_at: str
    items: list[KeyItem]
    # Empty in the keys written before the per-question label: `question_ids`
    # rebuilds the mapping from the items then.
    questions: list[KeyQuestion] = Field(default_factory=list)

    def question_ids(self) -> dict[str, str]:
        """{`07-Q`: query_id}."""
        if self.questions:
            return {q.label_id: q.query_id for q in self.questions}
        return {
            f"{i.label_id.split('-')[0]}-{QUESTION_SUFFIX}": i.query_id
            for i in self.items
        }


def question_label_id(number: int) -> str:
    return f"{number:02d}-{QUESTION_SUFFIX}"


def select_generators(
    answers: list[Answer], names: set[str]
) -> tuple[list[Answer], list[str]]:
    """(answers whose model is one of `names`, the other models, sorted). A model
    that stays in answers.jsonl but left the configuration never reaches the page."""
    kept = [a for a in answers if a.base in names]
    return kept, sorted({a.base for a in answers} - names)


def build_data(
    run_id: str,
    contexts: list[Context],
    answers: list[Answer],
    criteria: list[dict[str, str]],
    *,
    seed: int = 0,
    title: str = "Évaluation des réponses",
) -> tuple[dict[str, Any], Key, list[str]]:
    """(page data, key, warnings). `answers` are the effective answers of the run
    (one per model and question); only those with status `ok` are shown. The data
    holds no model name: only the key unblinds it."""
    by_query: dict[str, list[Answer]] = {}
    for answer in answers:
        if answer.status == "ok":
            by_query.setdefault(answer.query_id, []).append(answer)
    n_models = len({a.base for a in answers})

    warnings: list[str] = []
    questions: list[dict[str, Any]] = []
    key_items: list[KeyItem] = []
    key_questions: list[KeyQuestion] = []
    for number, context in enumerate(contexts, start=1):
        shown = sorted(by_query.get(context.query_id, []), key=lambda a: a.generator)
        if len(shown) < n_models:
            warnings.append(
                f"{context.query_id}: {len(shown)} answer(s) of {n_models} models"
            )
        if not shown:
            continue
        # One shuffle per question, reproducible from the seed alone.
        random.Random(f"{seed}:{context.query_id}").shuffle(shown)
        entries = []
        for letter, answer in zip(_letters(len(shown)), shown, strict=True):
            label_id = f"{number:02d}-{letter}"
            entries.append(
                {
                    "label_id": label_id,
                    "letter": letter,
                    "html": render_markdown(answer.answer or ""),
                }
            )
            key_items.append(
                KeyItem(
                    label_id=label_id,
                    item_id=answer.item_id,
                    generator=answer.base,
                    query_id=context.query_id,
                    answer_sha256=answer_sha256(answer),
                )
            )
        key_questions.append(
            KeyQuestion(label_id=question_label_id(number), query_id=context.query_id)
        )
        questions.append(
            {
                "number": number,
                "label_id": question_label_id(number),
                "text": context.text,
                "idcc": context.idcc,
                "idcc_name": context.idcc_name,
                "answers": entries,
                "sources": [
                    {
                        "name": "Fiches officielles",
                        "items": [_source(c) for c in context.fiches],
                    },
                    {
                        "name": "Code du travail",
                        "items": [_source(c) for c in context.code],
                    },
                    {
                        "name": "Convention collective",
                        "items": [_source(c) for c in context.idcc_chunks],
                    },
                    {
                        "name": "Jurisprudence",
                        "items": [_source(c) for c in context.jurisprudence],
                    },
                ],
            }
        )
    if not key_items:
        raise ValueError("no answer to label: run `generate` first")

    digest = hashlib.sha256()
    for item in key_items:
        digest.update(f"{item.label_id}|{item.answer_sha256}|".encode())
    dataset_id = digest.hexdigest()[:10]
    data = {
        "title": title,
        "dataset_id": dataset_id,
        "criteria": criteria,
        "values": list(VALUES),
        "questions": questions,
    }
    key = Key(
        dataset_id=dataset_id,
        run_id=run_id,
        seed=seed,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        items=key_items,
        questions=key_questions,
    )
    return data, key, warnings


def render_page(
    data: dict[str, Any] | None = None, vault: dict[str, Any] | None = None
) -> str:
    """The labelling page: with `data`, self-contained (no network); without, the
    password screen that unlocks `vault` and fetches the data (see publish.py)."""
    # The vault first: the data (model text) is inserted last, so nothing in it can
    # be taken for the other placeholder.
    return (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__VAULT__", _json_for_script(vault))
        .replace("__DATA__", _json_for_script(data))
    )


def build_page(
    run_id: str,
    contexts: list[Context],
    answers: list[Answer],
    criteria: list[dict[str, str]],
    *,
    seed: int = 0,
    title: str = "Évaluation des réponses",
) -> tuple[str, Key, list[str]]:
    """(html, key, warnings): the self-contained page of `build_data`."""
    data, key, warnings = build_data(
        run_id, contexts, answers, criteria, seed=seed, title=title
    )
    return render_page(data), key, warnings


class HumanLabel(BaseModel):
    item_id: str
    generator: str
    query_id: str
    annotator: str
    labels: dict[str, bool]  # criterion -> True for "Oui"
    comment: str = ""
    flag: bool = False
    seconds: float | None = None


class QuestionLabel(BaseModel):
    """Were the sources given to the models enough to answer the question?"""

    query_id: str
    annotator: str
    sources_suffisantes: bool
    comment: str = ""


class LabelImportError(ValueError):
    pass


LABELS_FORMAT = "answers-labelling/1"


def _csv_rows(path: Path) -> list[tuple[str, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = {"label_id", *(c.value for c in CRITERIA)} - set(
            reader.fieldnames or []
        )
        if missing:
            raise LabelImportError(f"{path}: missing columns {sorted(missing)}")
        return [(f"{path}:{n}", row) for n, row in enumerate(reader, start=2)]


def _json_rows(path: Path, key: Key) -> list[tuple[str, dict[str, str]]]:
    """Rows of a labels file of the hosted page (`labels/<name>.json`), shaped like
    CSV rows."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != LABELS_FORMAT:
        raise LabelImportError(f"{path}: not a labels file ({LABELS_FORMAT})")
    if doc.get("dataset_id") != key.dataset_id:
        raise LabelImportError(
            f"{path}: labels of another build of the page (dataset "
            f"{doc.get('dataset_id')}, the key is {key.dataset_id})"
        )
    rows = []
    for label_id, entry in doc.get("labels", {}).items():
        row = {k: str(v) for k, v in entry.items() if k not in ("flag", "seconds")}
        row["flag"] = "1" if entry.get("flag") else ""
        row["seconds"] = str(entry.get("seconds") or "")
        rows.append((f"{path} [{label_id}]", {"label_id": label_id, **row}))
    return rows


def import_labels(
    path: Path, key: Key, answers: list[Answer], annotator: str
) -> tuple[list[HumanLabel], list[QuestionLabel], list[str]]:
    """Complete labels of a CSV exported by the page, or of the JSON file the hosted
    page saves in the data repo: answer labels, question labels (`07-Q`), and the
    label_ids left incomplete. A CSV without the sources column (made before the
    question label existed) gives no question label.

    Stops on an unknown label_id, a value other than Oui/Non, or an answer that
    changed since the page was built (the labels would not be about it)."""
    by_label = {i.label_id: i for i in key.items}
    by_question = key.question_ids()
    current = {a.item_id: answer_sha256(a) for a in answers if a.status == "ok"}
    labels: list[HumanLabel] = []
    question_labels: list[QuestionLabel] = []
    incomplete: list[str] = []
    rows = _json_rows(path, key) if path.suffix == ".json" else _csv_rows(path)
    for where, row in rows:
        label_id = (row.get("label_id") or "").strip()
        if label_id in by_question:
            value = (row.get(SOURCES_COLUMN) or "").strip()
            comment = (row.get("comment") or "").strip()
            if value and value not in VALUES:
                raise LabelImportError(
                    f"{where}: {SOURCES_COLUMN} = {value!r} is not one of {VALUES}"
                )
            if value:
                question_labels.append(
                    QuestionLabel(
                        query_id=by_question[label_id],
                        annotator=annotator,
                        sources_suffisantes=value == "Oui",
                        comment=comment,
                    )
                )
            elif comment:
                incomplete.append(label_id)
            continue
        item = by_label.get(label_id)
        if item is None:
            raise LabelImportError(f"{where}: unknown {label_id!r}")
        if current.get(item.item_id) != item.answer_sha256:
            raise LabelImportError(
                f"{where}: the answer behind {label_id} changed since the page was "
                "built"
            )
        values = {c.value: (row.get(c.value) or "").strip() for c in CRITERIA}
        for criterion, value in values.items():
            if value and value not in VALUES:
                raise LabelImportError(
                    f"{where}: {criterion} = {value!r} is not one of {VALUES}"
                )
        if not all(values.values()):
            if any(values.values()):
                incomplete.append(label_id)
            continue
        seconds = (row.get("seconds") or "").strip()
        labels.append(
            HumanLabel(
                item_id=item.item_id,
                generator=item.generator,
                query_id=item.query_id,
                annotator=annotator,
                labels={c: v == "Oui" for c, v in values.items()},
                comment=(row.get("comment") or "").strip(),
                flag=bool((row.get("flag") or "").strip()),
                seconds=float(seconds) if seconds else None,
            )
        )
    return labels, question_labels, incomplete


def judge_dataset(
    labels: list[HumanLabel], answers: list[Answer], contexts: list[Context]
) -> list[dict[str, str]]:
    """The labels in the format of `dataset/18q_human.json`, for `judge-eval`."""
    texts = {c.query_id: c.text for c in contexts}
    by_item = {a.item_id: a for a in answers}
    order = {c.query_id: i for i, c in enumerate(contexts)}
    rows = []
    for label in sorted(labels, key=lambda h: (order[h.query_id], h.item_id)):
        rows.append(
            {
                "id": label.item_id,
                "question": texts[label.query_id],
                "reponse": by_item[label.item_id].answer or "",
                **{c: "Oui" if v else "Non" for c, v in label.labels.items()},
            }
        )
    return rows


def load_human_labels(directory: Path) -> dict[str, dict[str, HumanLabel]]:
    """{annotator: {item_id: label}} from the `human-<annotator>.jsonl` files."""
    out: dict[str, dict[str, HumanLabel]] = {}
    for path in sorted(directory.glob("human-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                label = HumanLabel.model_validate_json(line)
                out.setdefault(label.annotator, {})[label.item_id] = label
    return out


def load_question_labels(directory: Path) -> dict[str, dict[str, QuestionLabel]]:
    """{annotator: {query_id: label}} from the `question-labels-<annotator>.jsonl`
    files."""
    out: dict[str, dict[str, QuestionLabel]] = {}
    for path in sorted(directory.glob("question-labels-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                label = QuestionLabel.model_validate_json(line)
                out.setdefault(label.annotator, {})[label.query_id] = label
    return out


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
