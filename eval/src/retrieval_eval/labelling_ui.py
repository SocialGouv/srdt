"""A self-contained HTML page to label a sampling key, one pair at a time.

The page embeds the questions and the document texts of the key, shows the guideline,
autosaves the labels in the browser (localStorage) and exports a CSV whose columns
`audit_id`, `grade`, `comment` are the ones `import_sheet` reads. Nothing leaves the
machine and the page is blind like the CSV sheet: no model grade, no retrieval
provenance.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path

from retrieval_eval.audit import SHEET_MAX_CHARS, AuditItem
from retrieval_eval.data import DocRecord, Query

TEMPLATE = Path(__file__).parent / "templates" / "labelling.html"
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# "- **2 — répond directement.** Le document ..." in the guideline
_GRADE_LINE = re.compile(r"\*\*\s*([012])\s*[—–-]\s*([^*]+?)\.?\s*\*\*")
TRUNCATION = "\n[… document tronqué : la suite dépasse la limite de la comparaison]"


def grade_names(guideline: str) -> dict[int, str]:
    """The short name of each grade, read from the guideline so the buttons cannot
    drift from it."""
    return {int(g): name.strip() for g, name in _GRADE_LINE.findall(guideline)}


def dataset_id(items: Sequence[AuditItem]) -> str:
    """Identifies the sheet, so that labels saved in the browser for another sample
    are never shown against this one."""
    digest = hashlib.sha256()
    for item in items:
        digest.update(f"{item.audit_id}|{item.query_id}|{item.doc_id}|".encode())
        digest.update(item.text_sha256.encode())
    return digest.hexdigest()[:10]


def _json_for_script(data: object) -> str:
    """JSON safe inside a <script> element. Every `<` becomes the JSON escape
    `\\u003c`, so no `</script>` or `<!--` can occur whatever the text holds; U+2028
    and U+2029 are escaped too (they end a line in older JavaScript parsers)."""
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build_labelling_html(
    items: Sequence[AuditItem],
    queries: dict[str, Query],
    docs: dict[str, DocRecord],
    guideline: str,
    title: str = "Relevance labelling",
) -> tuple[str, list[AuditItem]]:
    """The page, and the items it contains. Pairs whose document text is missing or
    changed since the key was drawn are left out, as `export_sheet` does."""
    guideline = _HTML_COMMENT.sub("", guideline).strip()
    kept: list[AuditItem] = []
    rows = []
    for item in items:
        doc = docs.get(item.doc_id)
        if doc is None or doc.text_sha256 != item.text_sha256:
            continue
        query = queries[item.query_id]
        text = doc.text
        if len(text) > SHEET_MAX_CHARS:
            text = text[:SHEET_MAX_CHARS] + TRUNCATION
        rows.append(
            {
                "audit_id": item.audit_id,
                "query": query.text,
                "idcc": query.idcc,
                "title": doc.title,
                "source": doc.source,
                "url": doc.url,
                "text": text,
                "chars": len(doc.text),
            }
        )
        kept.append(item)
    if not rows:
        raise ValueError("no pair of the key has a usable document text")
    data = {
        "title": title,
        "dataset_id": dataset_id(kept),
        "guideline": guideline,
        "grade_names": grade_names(guideline),
        "items": rows,
    }
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "__DATA__", _json_for_script(data)
    )
    return html, kept
