"""Judge the generated answers with judge_eval's judges and prompts.

The judgements live in `runs/<run_id>/judge/`, a judge_eval run directory
(`config.json` + `predictions.jsonl`), one item per (generator, question):
`<generator>::<query_id>`. Only answers with status `ok` are judged.
"""

from pathlib import Path

from answer_eval.contexts import Context
from answer_eval.generate import Answer
from judge_eval.data import Item

JUDGE_DIR = "judge"


def answer_items(answers: list[Answer], contexts: list[Context]) -> list[Item]:
    """Items in question order then generator order; `question_id` is the index of
    the question, so that answers to the same question are grouped."""
    index = {c.query_id: i for i, c in enumerate(contexts)}
    texts = {c.query_id: c.text for c in contexts}
    items = [
        Item(
            id=a.item_id,
            question_id=index[a.query_id],
            question=texts[a.query_id],
            answer=a.answer or "",
        )
        for a in answers
        if a.status == "ok" and a.query_id in index
    ]
    return sorted(items, key=lambda i: (i.question_id, i.id))


def judge_dir(run_dir: Path) -> Path:
    return run_dir / JUDGE_DIR
