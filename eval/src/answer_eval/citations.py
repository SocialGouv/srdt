"""Mechanical check of the citation rule of the web prompt.

The prompt asks for quotes in a dedicated block (`> *"passage"* — [title](url)`),
copied word for word from the knowledge base, and forbids any URL it did not give.
This counts, per answer, the quote lines, those found verbatim in the sources, the
links, and the links absent from the prompt the model received.

It is a rough signal, not a judgement: the comparison ignores case, spaces and
punctuation (the indexed texts space punctuation oddly), a quote cut with `[...]` or
`…` is checked piece by piece, and a link to a real page is still counted as unknown
when the prompt did not contain it.
"""

import re
import unicodedata

from pydantic import BaseModel

from answer_eval.contexts import Context
from answer_eval.generate import Answer, render
from answer_eval.prompt import WebPrompts

QUOTE = re.compile(r"^>\s*\*?[«\"“](.+?)[»\"”]\*?\s*[—–-]", re.MULTILINE)
LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
URL = re.compile(r"https?://[^\s)\]>\"'`]+")
CUT = re.compile(r"\[\.\.\.\]|\[…\]|…|\.\.\.")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("œ", "oe")
    return re.sub(r"[^0-9a-zà-ÿ]", "", text)


def _url(url: str) -> str:
    return url.rstrip(".,;").rstrip("/")


class CitationCheck(BaseModel):
    quotes: int
    verbatim: int
    links: int
    unknown_links: list[str]


def check_answer(text: str, sources: str, known_urls: set[str]) -> CitationCheck:
    """`sources`: the normalised text of the chunks; `known_urls`: every URL of the
    prompt."""
    quotes = QUOTE.findall(text)
    verbatim = sum(
        all(_norm(piece) in sources for piece in CUT.split(quote) if _norm(piece))
        for quote in quotes
    )
    links = LINK.findall(text)
    unknown = sorted({u for u in links if _url(u) not in known_urls})
    return CitationCheck(
        quotes=len(quotes), verbatim=verbatim, links=len(links), unknown_links=unknown
    )


def check_answers(
    prompts: WebPrompts, contexts: list[Context], answers: list[Answer]
) -> dict[str, CitationCheck]:
    """{item_id: check} for the answers with status `ok`."""
    by_query = {}
    for context in contexts:
        chunks = [
            *context.fiches,
            *context.code,
            *context.idcc_chunks,
            *context.jurisprudence,
        ]
        system = render(prompts, context)[0]["content"]
        by_query[context.query_id] = (
            _norm(" ".join(c.content for c in chunks)),
            {_url(u) for u in URL.findall(system)},
        )
    return {
        a.item_id: check_answer(a.answer or "", *by_query[a.query_id])
        for a in answers
        if a.status == "ok" and a.query_id in by_query
    }
