"""Stage 1: find the passages that talk about heat.

An anchor is a line that matches a heat term. The passage is the section of the
agreement that holds it (same sections as the ingestion chunks), or a window of lines
around the anchor when the section is long or the agreement has no headings.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field

from ingestion.sources.accords import split_sections

from acco_analysis.corpus import Agreement

# The four phrases the agreements were collected with (the API stems them, so the
# singular and plural forms, and "caniculaire(s)", all match).
PHRASES = (
    r"canicules?",
    r"caniculaires?",
    r"fortes? chaleurs?",
    r"vagues? de chaleurs?",
)
# Other ways to say it: not what the agreements were collected with.
VARIANTS = (
    r"chaleurs?",
    r"temp[ée]ratures? (?:[ée]lev[ée]es?|extr[êe]mes?|excessives?|caniculaires?)",
    r"(?:fortes?|hautes?) temp[ée]ratures?",
    r"stress thermique",
    r"contraintes? thermiques?",
    r"coups? de chaleur",
    r"pics? de chaleur",
    r"[ée]pisodes? (?:de chaleur|climatiques?)",
    r"intemp[ée]ries? climatiques?",
)

PHRASE_RE = re.compile("|".join(PHRASES), re.I)
VARIANT_RE = re.compile("|".join(VARIANTS), re.I)

# a section up to this long is one passage; a longer one is cut around its anchors
MAX_SECTION_CHARS = 3000
LINES_BEFORE = 2
LINES_AFTER = 3
MAX_PASSAGE_CHARS = 3500


@dataclass
class Anchor:
    term: str  # as written, lower case
    kind: str  # "phrase" (collection terms) or "variant"
    line: int  # index in the section's lines, -1 for the heading


@dataclass
class Passage:
    id: str  # {agreement id}-{section index}[-{n} when a section gives several]
    agreement_id: str
    section: int  # same index as the ingestion chunk ids
    heading: str  # breadcrumb, without the agreement title
    text: str
    anchors: list[Anchor] = field(default_factory=list)
    windowed: bool = False  # cut out of a longer section
    start: int = 0  # [start, stop) line range in the section's lines
    stop: int = 0

    @property
    def in_heading(self) -> bool:
        return any(a.line == -1 for a in self.anchors)

    def to_json(self) -> dict:
        return asdict(self)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def find_anchors(text: str, line: int = 0) -> list[Anchor]:
    text = _fold(text)
    found: list[Anchor] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in (("phrase", PHRASE_RE), ("variant", VARIANT_RE)):
        for m in pattern.finditer(text):
            # "fortes chaleurs" is not also a "chaleurs" variant
            if any(s <= m.start() and m.end() <= e for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            found.append(Anchor(m.group(0).lower(), kind, line))
    return found


def _windows(centers: list[int], n_lines: int) -> list[tuple[int, int]]:
    """Merged [start, stop) line ranges around the anchor lines."""
    ranges: list[tuple[int, int]] = []
    for c in sorted(centers):
        start, stop = max(0, c - LINES_BEFORE), min(n_lines, c + LINES_AFTER + 1)
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(stop, ranges[-1][1]))
        else:
            ranges.append((start, stop))
    return ranges


def extract_passages(agreement: Agreement) -> list[Passage]:
    passages: list[Passage] = []
    for index, section in enumerate(split_sections(agreement.text)):
        heading = " > ".join(section.breadcrumb)
        lines = section.lines
        heading_anchors = find_anchors(heading, line=-1) if heading else []
        line_anchors = [find_anchors(line, i) for i, line in enumerate(lines)]
        centers = [i for i, found in enumerate(line_anchors) if found]
        if not heading_anchors and not centers:
            continue

        base = f"{agreement.id}-{index}"
        if sum(len(line) for line in lines) <= MAX_SECTION_CHARS:
            ranges = [(0, len(lines))]
        else:
            # a heading about heat: the start of the section, then the windows
            ranges = _windows(([0] if heading_anchors else []) + centers, len(lines))

        for n, (start, stop) in enumerate(ranges):
            anchors = [a for i in range(start, stop) for a in line_anchors[i]]
            if start == 0:
                anchors = heading_anchors + anchors
            if not anchors:
                continue
            text = "\n".join(lines[start:stop])[:MAX_PASSAGE_CHARS]
            passages.append(
                Passage(
                    id=base if len(ranges) == 1 else f"{base}-{n}",
                    agreement_id=agreement.id,
                    section=index,
                    heading=heading,
                    text=text,
                    anchors=anchors,
                    windowed=(start, stop) != (0, len(lines)),
                    start=start,
                    stop=stop,
                )
            )
    return passages
