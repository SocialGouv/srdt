"""Company agreements from the Légifrance ACCO fund (accords d'entreprise), as
snapshotted by `ingest fetch acco --from-dir`: one JSON file per agreement (the
/consult/acco response of the DILA API), one chunk group per section."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ingestion.contract import Chunk
from ingestion.text.chunker import Chunker
from ingestion.text.office import OfficeError, extract_text

accords_uri = "https://www.legifrance.gouv.fr/acco/id"

# The API cuts the extracted text at 100,000 characters (some at 99,9xx): from this
# length, the text is read again from the original file.
TRUNCATION_THRESHOLD = 99_000
ORIGINAL_SUFFIXES = (".docx", ".odt")

# a section whose text is shorter is a title with nothing under it
MIN_BODY_CHARS = 15
# at least this many headings of a kind for the agreement to be split on it
MIN_HEADINGS = 3
# a longer line is a paragraph that starts with its heading, not a heading
MAX_HEADING_CHARS = 150
MAX_NUMBERED_HEADING_CHARS = 100

_NUMBER = r"(?:\d+(?:[.\-]\d+)*(?:\s?(?:bis|ter|quater))?|premier|1er|unique|[ivx]+)"
ARTICLE = re.compile(
    rf"^(?:[-–•·]\s*)?(?:article|art\.?)\s*(?:n°\s*)?{_NUMBER}\b", re.I
)
PART = re.compile(
    r"^(?:titre|chapitre|partie|section)\s+(?:\d+|[ivx]+|premier|préliminaire|unique)\b",
    re.I,
)
NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s*[.):–—-]?\s+(?=[A-ZÀ-Ý])")
ROMAN = re.compile(r"^[IVX]{1,5}\s*[.)–—-]\s*(?=[A-ZÀ-Ý])")

# what follows "Article 3" for it to be a heading: nothing, a separator, or a title
# (not the rest of a sentence: "Article 3 du présent accord")
_HEADING_TAIL = re.compile(r"^(?:\s*$|\s*[.:–—-]|\s+[A-ZÀ-Ý0-9«\"'’(])")

# blanks to fill in ("Nom : ........"), no use in a chunk and no separator to split on
FILL_IN = re.compile(r"[._…]{4,}")

# table of contents: a "sommaire" marker, and lines ending with a page number
TOC_MARKER = re.compile(r"^(?:sommaire|table des mati[eè]res)\s*:?\s*$", re.I)
_PAGE = r"(?:p(?:age)?\.?\s*)?\d{1,3}\s*$"
TOC_LINE = re.compile(rf"(?:\t|\.{{2,}}|[  ]{{2,}})\s*{_PAGE}")
TOC_BLOCK_LINE = re.compile(rf"(?:[\s ]|\.{{2,}}){_PAGE}")
MAX_TOC_LINE_CHARS = 200


@dataclass
class Heading:
    level: int  # 1: title, chapter, part; 2: article or numbered section
    label: str
    # text of the line after the heading, when the heading starts a paragraph
    rest: str = ""


@dataclass
class Section:
    breadcrumb: list[str]
    lines: list[str] = field(default_factory=list)


def is_agreement_file(name: str) -> bool:
    return name.startswith("ACCOTEXT") and name.endswith(".json")


def original_file(directory: Path, agreement_id: str) -> Path | None:
    for suffix in ORIGINAL_SUFFIXES:
        path = directory / f"{agreement_id}{suffix}"
        if path.exists():
            return path
    return None


def normalise_agreement(data: dict[str, Any], directory: Path) -> dict[str, Any]:
    """The agreement as stored in a snapshot: without the base64 copy of the original
    file, and with the full text when the API cut it. `directory` holds the original
    files (`<id>.docx` or `<id>.odt`). `attachment.content_source` tells where the
    text comes from: "api", "docx", "odt", or "api-truncated" when the API text looks
    cut and the original could not be read."""
    agreement = dict(data["acco"])
    agreement.pop("data", None)
    attachment = dict(agreement.get("attachment") or {})
    content = attachment.get("content") or ""
    source = "api"

    if len(content) >= TRUNCATION_THRESHOLD:
        source = "api-truncated"
        original = original_file(directory, agreement["id"])
        if original:
            try:
                full = extract_text(original)
            except OfficeError:
                pass
            else:
                if len(full) > len(content):
                    content, source = full, original.suffix.lstrip(".")
                else:
                    source = "api"  # the file is not longer: the text was complete

    attachment["content"] = content
    attachment["content_source"] = source
    agreement["attachment"] = attachment
    return {**data, "acco": agreement}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", FILL_IN.sub("…", text)).strip()


def _heading_tail_ok(text: str, end: int) -> bool:
    return _HEADING_TAIL.match(text[end:]) is not None


def _split_heading(text: str, end: int) -> tuple[str, str]:
    """(label, rest): the whole line is the label when it is short."""
    if len(text) <= MAX_HEADING_CHARS:
        return _clean(text), ""
    return _clean(text[:end]), _clean(text[end:]).lstrip(".:–—- ")


def _article_heading(text: str) -> Heading | None:
    m = ARTICLE.match(text)
    if m and _heading_tail_ok(text, m.end()):
        label, rest = _split_heading(text, m.end())
        return Heading(2, label, rest)
    m = PART.match(text)
    if m and len(text) <= MAX_HEADING_CHARS and _heading_tail_ok(text, m.end()):
        return Heading(1, _clean(text))
    return None


def _numbered_heading(text: str) -> Heading | None:
    if len(text) > MAX_NUMBERED_HEADING_CHARS or text.endswith((";", ",")):
        return None
    m = NUMBERED.match(text)
    if m:
        # "1. Salaires" is a title, "1.1 Durée" is a section of it
        return Heading(2 if "." in m.group(1) else 1, _clean(text))
    if ROMAN.match(text):
        return Heading(1, _clean(text))
    return None


def _looks_like_heading(text: str) -> bool:
    return bool(
        _article_heading(text)
        or _numbered_heading(text)
        or (text.isupper() and len(text) > 3)
    )


def strip_toc(lines: list[str]) -> list[str]:
    """Remove the table of contents: its titles repeat the headings of the text, and
    carry no clause."""
    kept: list[str] = []
    in_toc = False
    for line in lines:
        text = line.strip()
        if TOC_MARKER.match(text):
            in_toc = True
            continue
        if in_toc:
            if not text or (
                len(text) <= MAX_TOC_LINE_CHARS and TOC_BLOCK_LINE.search(text)
            ):
                continue
            in_toc = False
        if (
            len(text) <= MAX_TOC_LINE_CHARS
            and TOC_LINE.search(text)
            and _looks_like_heading(text)
        ):
            continue
        kept.append(line)
    return kept


def split_sections(text: str) -> list[Section]:
    """Sections of the agreement, headed by their breadcrumb (part > article).

    Splits on "Article N" headings; without enough of them, on numbered headings
    ("1. Salaires", "1.1 Durée"); without those either, one section."""
    lines = [
        _clean(line)
        for line in strip_toc(text.replace("\r", "").split("\n"))
        if line.strip()
    ]
    detect = _article_heading
    if sum(1 for line in lines if _article_heading(line)) < MIN_HEADINGS:
        detect = _numbered_heading
        if sum(1 for line in lines if _numbered_heading(line)) < MIN_HEADINGS:
            return [Section([], lines)]

    sections = [Section([])]
    part: str | None = None
    for line in lines:
        heading = detect(line)
        if heading is None:
            sections[-1].lines.append(line)
            continue
        if heading.level == 1:
            part = heading.label
            breadcrumb = [heading.label]
        else:
            breadcrumb = [part, heading.label] if part else [heading.label]
        sections.append(Section(breadcrumb, [heading.rest] if heading.rest else []))
    return sections


def _idcc(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    return str(int(text)) if text.isdigit() else text


def _date(milliseconds: Any) -> str | None:
    if not isinstance(milliseconds, int | float):
        return None
    return datetime.fromtimestamp(milliseconds / 1000, UTC).date().isoformat()


def _labels(items: Any) -> list[str]:
    return [i["libelle"] for i in items or [] if i.get("libelle")]


def chunk_accord(data: dict[str, Any], chunker: Chunker) -> list[Chunk]:
    agreement = data["acco"]
    agreement_id = agreement["id"]
    text = (agreement.get("attachment") or {}).get("content") or ""

    agreement_title = _clean(agreement.get("titreTexte") or "") or agreement_id
    company = _clean(agreement.get("raisonSociale") or "")
    common: dict[str, Any] = {
        "source": "accords_entreprise",
        "url": f"{accords_uri}/{agreement_id}",
        "initial_id": agreement_id,
        "title": f"{company} — {agreement_title}" if company else agreement_title,
        "idcc": _idcc(agreement.get("codeIdcc")),
        "articles": [],
        "themes": _labels(agreement.get("themes")),
        "unions": _labels(agreement.get("syndicats")),
    }
    # absent rather than null when the API has no value
    for key, value in {
        "company": company,
        "siret": agreement.get("siret"),
        "sector": agreement.get("secteur"),
        "nature": agreement.get("nature"),
        "signature_date": _date(agreement.get("dateTexte")),
    }.items():
        if value:
            common[key] = value

    chunks: list[Chunk] = []
    for section_idx, section in enumerate(split_sections(text)):
        body = "\n".join(section.lines).strip()
        if len(body) < MIN_BODY_CHARS:
            continue
        header = " > ".join([agreement_title, *section.breadcrumb])
        id = f"{agreement_id}-{section_idx}"
        for idx, split in enumerate(chunker.split_character_recursive(body)):
            chunks.append(
                Chunk.model_validate(
                    {
                        "content": f"{header}\n{split.page_content}",
                        "id": id,
                        "metadata": {**common, "id": id, "idx": idx},
                    }
                )
            )
    return chunks
