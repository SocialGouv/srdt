import re
from typing import Protocol

from srdt_analysis.api.schemas import ChunkResult, CitedArticle
from srdt_analysis.clients.elastic_handler import ArticleChunk
from srdt_analysis.core.constants import CHUNK_INDEX
from srdt_analysis.text.article_citations import (
    ArticleCitation,
    extract_article_citations,
)

# a question rarely cites more than a handful of articles: past this we are
# looking at pasted text and the numbers are no longer a precise request
MAX_CITED_NUMBERS = 20


class ArticleChunkSource(Protocol):
    def get_chunks_by_articles(
        self, index_name: str, nums: list[str]
    ) -> list[ArticleChunk]: ...


def _variants(citation: ArticleCitation) -> list[str]:
    # a number cited without its letter ("4121-1 du code du travail") can be
    # a legislative (L), regulatory (R) or decree (D) article
    if citation.has_letter:
        return [citation.num]
    return [f"{letter}{citation.num}" for letter in "LRD"]


def _usable(citations: list[ArticleCitation]) -> list[ArticleCitation]:
    # "unknown" is treated as the Code du travail; another code is never searched
    return [c for c in citations if c.code != "other"]


def _holds_text(chunk: ArticleChunk, num: str) -> bool:
    # chunks are "Article L1226-14 \n text": the number of a section split in
    # several chunks is on every one of them, the text on only one
    marker = rf"Article\s+{num[0]}\.?\s?{re.escape(num[1:])}(?![\w-])"
    return re.search(marker, chunk.chunk.content) is not None


def pick_chunks(
    citations: list[ArticleCitation], hits: list[ArticleChunk], max_chunks: int
) -> tuple[list[ChunkResult], list[CitedArticle]]:
    """One chunk per cited article, in order of citation, without duplicates
    (articles of the same section share their chunk)."""
    chunks: list[ChunkResult] = []
    seen: set[str] = set()
    statuses: list[CitedArticle] = []

    for citation in citations:
        found = False
        if citation.code != "other":
            for num in _variants(citation):
                holders = sorted(
                    (h for h in hits if num in h.nums), key=lambda h: h.idx
                )
                if not holders:
                    continue
                found = True
                # the chunk holding the text, else the start of the section
                picked = [h for h in holders if _holds_text(h, num)] or holders[:1]
                for hit in picked:
                    if hit.chunk.id_chunk not in seen and len(chunks) < max_chunks:
                        seen.add(hit.chunk.id_chunk)
                        # not a similarity result: the user named the article
                        chunks.append(hit.chunk.model_copy(update={"score": 1.0}))
        statuses.append(
            CitedArticle(
                num=citation.num, raw=citation.raw, kind=citation.kind, found=found
            )
        )

    return chunks, statuses


def find_cited_articles(
    question: str, es: ArticleChunkSource, max_chunks: int
) -> tuple[list[ChunkResult], list[CitedArticle]]:
    citations = extract_article_citations(question)
    nums = list(dict.fromkeys(num for c in _usable(citations) for num in _variants(c)))[
        :MAX_CITED_NUMBERS
    ]
    hits = es.get_chunks_by_articles(CHUNK_INDEX, nums)
    return pick_chunks(citations, hits, max_chunks)
