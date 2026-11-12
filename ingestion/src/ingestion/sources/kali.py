"""Collective agreements from the KALI JSON files (@socialgouv/kali-data format),
one chunk group per article (ported from the api's ingestion/agreements.py)."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup

from ingestion.contract import Chunk
from ingestion.sources.models import KaliKind, RawKaliLink, ResolvedKaliLink
from ingestion.text.chunker import Chunker

conventions_uri = "https://www.legifrance.gouv.fr/conv_coll/id"

# "Textes Salaires" is left out
MAIN_PARTS = ["Texte de base", "Textes Attachés"]


def is_agreement_file(name: str) -> bool:
    return name.startswith("KALICONT") and name.endswith(".json")


def _find_main_part(children, prefix):
    return next(
        (c for c in children if c.get("data", {}).get("title", "").startswith(prefix)),
        None,
    )


def _walk_articles(node, breadcrumb):
    if node.get("type") == "article":
        yield (breadcrumb, node)
        return
    title = node.get("data", {}).get("title")
    child_breadcrumb = breadcrumb + [title] if title else breadcrumb
    for child in node.get("children", []):
        yield from _walk_articles(child, child_breadcrumb)


def _has_text(content) -> bool:
    return bool(content) and bool(
        BeautifulSoup(content, "html.parser").get_text(strip=True)
    )


def iter_chunkable_articles(data) -> Iterator[tuple[list[str], dict]]:
    """(breadcrumb, article data) of the articles of an agreement that become
    chunks: in the main parts, with some text."""
    children = data.get("children", [])

    for part in MAIN_PARTS:
        part_node = _find_main_part(children, part)

        if not part_node:
            continue

        for part_child in part_node.get("children", []):
            for breadcrumb, article in _walk_articles(part_child, [part]):
                article_data = article.get("data", {})
                if _has_text(article_data.get("content")):
                    yield breadcrumb, article_data


def chunk_cc(data, chunker: Chunker) -> list[Chunk]:
    chunks: list[Chunk] = []

    idcc = data.get("data", {}).get("num")

    for breadcrumb, article_data in iter_chunkable_articles(data):
        content = article_data["content"]
        article_num = article_data.get("num")

        last_breadcrumb = breadcrumb[len(breadcrumb) - 1]
        suffix = f" — Article {article_num}" if article_num else ""

        header = " > ".join(breadcrumb) + suffix
        title = last_breadcrumb + suffix

        id = article_data.get("id") or article_data.get("cid")

        for idx, split in enumerate(chunker.split_html_contribs(content)):
            chunks.append(
                Chunk.model_validate(
                    {
                        "content": f"{header}\n{split.page_content}",
                        "id": id,
                        "metadata": {
                            "id": id,
                            "source": "conventions",
                            "url": f"{conventions_uri}/{id}",
                            "initial_id": id,
                            "title": title,
                            "idx": idx,
                            "idcc": str(idcc),
                            "articles": [],
                        },
                    }
                )
            )

    return chunks


@dataclass(slots=True)
class KaliTarget:
    kind: KaliKind
    id: str
    cid: str
    num: str | None
    idcc: str | None
    container: str | None
    # metadata.id of the conventions chunks of the article, None if it has none
    chunk_id: str | None = None


class KaliIndex:
    """Resolve KALIARTI/KALITEXT/KALISCTA ids (including old article versions,
    through the cid) against the agreements.

    An attached text is shared by several agreements: its ids have one target
    per agreement, the url container picks the right one.
    """

    def __init__(self, agreements: Iterable[dict]):
        self._by_id: dict[str, list[KaliTarget]] = {}
        for data in agreements:
            self._add_agreement(data)

    def _add_agreement(self, data: dict):
        header = data.get("data", {})
        num = header.get("num")
        idcc = str(num) if num is not None else None
        container = header.get("id")

        articles: dict[str, KaliTarget] = {}
        for child in data.get("children", []):
            self._walk(child, idcc, container, articles)

        for _, article_data in iter_chunkable_articles(data):
            id = article_data.get("id") or article_data.get("cid")
            if id in articles:
                articles[id].chunk_id = id

    def _walk(
        self,
        node: dict,
        idcc: str | None,
        container: str | None,
        articles: dict[str, KaliTarget],
    ):
        data = node.get("data", {})
        id = data.get("id") or data.get("cid")
        node_type = node.get("type")
        if id and node_type in ("article", "section"):
            target = KaliTarget(
                kind=node_type,
                id=id,
                cid=data.get("cid") or id,
                num=data.get("num"),
                idcc=idcc,
                container=container,
            )
            if node_type == "article":
                articles[id] = target
            for key in {target.id, target.cid}:
                self._by_id.setdefault(key, []).append(target)
        for child in node.get("children", []):
            self._walk(child, idcc, container, articles)

    def _target(self, raw: RawKaliLink) -> KaliTarget | None:
        targets = self._by_id.get(raw["kali_id"])
        if not targets:
            return None
        return next((t for t in targets if t.container == raw["container"]), targets[0])

    def resolve(self, raw: RawKaliLink) -> ResolvedKaliLink:
        target = self._target(raw)
        return {
            **raw,
            "container": target.container if target else raw["container"],
            "kind": target.kind if target else None,
            "cid": target.cid if target else None,
            "num": target.num if target else None,
            "idcc": target.idcc if target else None,
            "chunk_id": target.chunk_id if target else None,
            "canonical_url": f"{conventions_uri}/{target.id}" if target else None,
        }

    def resolve_all(self, raws: Iterable[RawKaliLink]) -> list[ResolvedKaliLink]:
        """Resolve and deduplicate (on the resolved cid, else the raw id):
        the first occurrence is kept."""
        links: list[ResolvedKaliLink] = []
        seen: set[str] = set()
        for raw in raws:
            link = self.resolve(raw)
            key = link["cid"] or link["kali_id"]
            if key not in seen:
                seen.add(key)
                links.append(link)
        return links
