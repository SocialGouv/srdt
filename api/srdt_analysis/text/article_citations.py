import re
from dataclasses import dataclass
from typing import Literal, Optional

# Extraction of the Code du travail articles a user cites in a question
# ("article L. 1226-14 du code du travail"). Plain regex, no tokenizer: it is
# meant for a targeted index lookup, so a wrong number only costs a miss.
#
# Article numbers of the Code du travail are a letter (L, R, D) followed by
# four digits, a hyphen and one to three digits, up to three hyphens in all
# (L1226-14, L4121-3-1). A bare number without hyphen ("L233", "article 4")
# is a convention clause or an old numbering, never resolvable: it is ignored.

CitationKind = Literal["article", "range-start", "range-end", "following"]
CitationCode = Literal["travail", "other", "unknown"]

CODE_WINDOW_AFTER = 90
CODE_WINDOW_BEFORE = 40
CODE_WINDOW_LETTERLESS = 30

_HYPHEN = r"[-–‑]"

# "article" / "art." right before a letter makes a lowercase letter acceptable
_LETTERED = re.compile(
    rf"(?P<pre>\b(?:articles?|art)\b\.?\s*)?"
    rf"(?<![A-Za-z0-9])(?P<letter>[LRDlrd])\s?[.\-]?\s?"
    rf"(?P<num>\d{{1,4}}(?:{_HYPHEN}\d{{1,3}}){{1,3}})(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# "articles 4121-1 et 4121-2 du code du travail": the letter is missing, the
# code name is what makes the number credible
_LETTERLESS = re.compile(
    rf"(?<![A-Za-z0-9\-–‑])(?P<num>[1-8]\d{{3}}(?:{_HYPHEN}\d{{1,3}}){{1,3}})"
    rf"(?![A-Za-z0-9\-–‑])"
)

_CODE_TRAVAIL = r"code\s+d[ue]\s+travail|c\.\s?trav\b\.?|(?-i:\bCT\b)"
_CODE_OTHER = (
    r"code\s+(?:de\s+l['’]\s?|de\s+la\s+|du\s+|des\s+|de\s+|d['’]\s?)?[\wéèêàç]+"
    r"|(?-i:\b(?:CSS|CASF|CJA|CPC|CSP|CGCT|CESEDA|CGI)\b)"
)
_SAME_CODE = r"m[êe]me\s+code"
_CODE_MENTION = re.compile(
    rf"(?P<travail>{_CODE_TRAVAIL})|(?P<same>{_SAME_CODE})|(?P<other>{_CODE_OTHER})",
    re.IGNORECASE,
)

_RANGE_LINK = re.compile(r"\s*(?:à|au|jusqu['’]à)\s*$", re.IGNORECASE)
_LIST_LINK = re.compile(r"\s*(?:,|;|et|ou|ainsi\s+que|à|au)?\s*", re.IGNORECASE)
_FOLLOWING = re.compile(r"\s*(?:et\s+suivants?|s\.?\s?suiv\.?)", re.IGNORECASE)


@dataclass
class ArticleCitation:
    # normalised number: "L1226-14", or "1226-14" when the letter is missing
    num: str
    raw: str
    kind: CitationKind
    code: CitationCode

    @property
    def has_letter(self) -> bool:
        return self.num[0].isalpha()


@dataclass
class _Match:
    start: int
    end: int
    raw: str
    num: str


def _normalise(letter: Optional[str], num: str) -> str:
    digits = re.sub(_HYPHEN, "-", num)
    return f"{letter.upper()}{digits}" if letter else digits


def _find_matches(text: str) -> list[_Match]:
    matches: list[_Match] = []

    for m in _LETTERED.finditer(text):
        letter = m.group("letter")
        # a lowercase letter alone is too ambiguous ("d'1", "l-3"): it is
        # only accepted right after "article" / "art."
        if letter.islower() and not m.group("pre"):
            continue
        start = m.start("letter")
        matches.append(
            _Match(
                start,
                m.end(),
                text[start : m.end()],
                _normalise(letter, m.group("num")),
            )
        )

    taken = [(m.start, m.end) for m in matches]
    for m in _LETTERLESS.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        window = text[m.end() : m.end() + CODE_WINDOW_LETTERLESS]
        mention = _CODE_MENTION.search(window)
        if mention and mention.group("travail"):
            matches.append(
                _Match(
                    m.start(), m.end(), m.group("num"), _normalise(None, m.group("num"))
                )
            )

    return sorted(matches, key=lambda m: m.start)


def _classify_mention(mention: re.Match, previous: CitationCode) -> CitationCode:
    if mention.group("travail"):
        return "travail"
    if mention.group("same"):
        return previous
    return "other"


def _attribute_codes(text: str, matches: list[_Match]) -> list[CitationCode]:
    codes: list[CitationCode] = []
    previous: CitationCode = "unknown"

    for i, match in enumerate(matches):
        next_start = matches[i + 1].start if i + 1 < len(matches) else len(text)
        after = text[match.end : min(next_start, match.end + CODE_WINDOW_AFTER)]
        mention = _CODE_MENTION.search(after)

        if mention is None:
            # code named before the number: "(C. trav., art L3141-8)"
            previous_end = matches[i - 1].end if i > 0 else 0
            before = text[
                max(previous_end, match.start - CODE_WINDOW_BEFORE) : match.start
            ]
            mentions = list(_CODE_MENTION.finditer(before))
            mention = mentions[-1] if mentions else None

        code = _classify_mention(mention, previous) if mention else "unknown"
        codes.append(code)
        previous = code

    # "articles L1226-14 et L1226-15 du code du travail": the members of a list
    # share the code named after the last one
    for i in range(len(matches) - 2, -1, -1):
        between = text[matches[i].end : matches[i + 1].start]
        if codes[i] == "unknown" and _LIST_LINK.fullmatch(between):
            codes[i] = codes[i + 1]

    return codes


def _kind(text: str, matches: list[_Match], i: int) -> CitationKind:
    match = matches[i]
    if _FOLLOWING.match(text, match.end):
        return "following"
    if i + 1 < len(matches) and _RANGE_LINK.match(
        text[match.end : matches[i + 1].start]
    ):
        return "range-start"
    if i > 0 and _RANGE_LINK.match(text[matches[i - 1].end : match.start]):
        return "range-end"
    return "article"


def extract_article_citations(question: str) -> list[ArticleCitation]:
    """Articles cited in the question, in order of appearance, one per mention.

    `code` is "travail" when the Code du travail is named around the number,
    "other" when another code is, "unknown" when none is: callers treat
    "unknown" as the Code du travail (a labour-law assistant) and skip "other".
    """
    matches = _find_matches(question)
    codes = _attribute_codes(question, matches)
    return [
        ArticleCitation(
            num=match.num,
            raw=match.raw,
            kind=_kind(question, matches, i),
            code=codes[i],
        )
        for i, match in enumerate(matches)
    ]
