"""Code du travail from the LEGI JSON (@socialgouv/legi-data format): chunking and
resolution of Legifrance links (ported from the api's ingestion/legi_data.py)."""

from collections.abc import Iterable
from dataclasses import dataclass

from ingestion.contract import Chunk
from ingestion.sources.models import LegiKind, RawLegiLink, ResolvedLegiLink
from ingestion.text.chunker import Chunker

CODE_DU_TRAVAIL_FILE = "LEGITEXT000006072050.json"

uri = "https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006072050"

articles_uri = "https://www.legifrance.gouv.fr/codes/article_lc"


def get_articles(node):
    articles = []
    for c in node["children"]:
        if "num" in c["data"]:
            articles.append(
                {"num": c["data"]["num"], "url": f"{articles_uri}/{c['data']['id']}"}
            )
    return articles


def get_text_flat(node):
    content = []
    for c in node["children"]:
        if "num" in c["data"]:
            content.append(f"\nArticle {c['data']['num']}")

        if "texte" in c["data"]:
            content.append(c["data"]["texte"])
        else:
            content = content + get_text_flat(c)

    return content


def _is_chunk_node(node) -> bool:
    # only the first child is checked: a node whose first child is an article
    # becomes a code du travail document (and so a chunk)
    return next(c["type"] == "article" for c in node["children"])


def recursive_lookup(path, node, chunker: Chunker) -> list[Chunk]:
    data = node["data"]

    if "title" not in data:
        return []

    title = data["title"]

    newPath = path + [title]

    if len(node["children"]) < 1:
        return []

    # if any of its children is an article, we flatten them and select the node
    elif _is_chunk_node(node):
        text = " \n ".join(get_text_flat(node))
        articles = get_articles(node)
        return [
            Chunk.model_validate(
                {
                    "content": split.page_content,
                    "id": data["cid"],
                    "metadata": {
                        "articles": articles,
                        "idx": idx,
                        "id": data["cid"],
                        "initial_id": data["cid"],
                        "url": f"{uri}/{data['cid']}",
                        "source": "code_du_travail",
                        "title": " ".join(newPath),
                        "idcc": None,
                    },
                }
            )
            for idx, split in enumerate(chunker.split_character_recursive(text))
        ]

    else:
        chunks = []
        for c in node["children"]:
            chunks = chunks + recursive_lookup(newPath, c, chunker)
        return chunks


def chunk_code_du_travail(code: dict) -> list[Chunk]:
    return recursive_lookup([], code, Chunker())


@dataclass
class LegiTarget:
    kind: LegiKind
    cid: str
    num: str | None
    # metadata.id of the code du travail chunks containing the article / section
    chunk_id: str | None
    canonical_url: str


class LegiIndex:
    """Resolve LEGIARTI/LEGISCTA ids (including old article versions) against
    the indexed code du travail.
    """

    def __init__(self, code: dict):
        self._by_id: dict[str, LegiTarget] = {}
        self._walk(code, chunk_id=None, reachable=True)

    def _walk(self, node, chunk_id: str | None, reachable: bool):
        data = node["data"]

        if node["type"] == "article":
            target = LegiTarget(
                kind="article",
                cid=data["cid"],
                num=data.get("num"),
                chunk_id=chunk_id,
                canonical_url=f"{articles_uri}/{data['id']}",
            )
            versions = [v["id"] for v in data.get("articleVersions") or []]
            self._register([data["id"], data["cid"], *versions], target)
            return

        # same rules as recursive_lookup to know which node becomes a chunk
        if reachable and chunk_id is None:
            if "title" not in data:
                reachable = False
            elif node["children"] and _is_chunk_node(node):
                chunk_id = data["cid"]

        if "cid" in data:
            target = LegiTarget(
                kind="section",
                cid=data["cid"],
                num=None,
                chunk_id=chunk_id,
                canonical_url=f"{uri}/{data['cid']}",
            )
            self._register([data.get("id"), data["cid"]], target)

        for child in node["children"]:
            self._walk(child, chunk_id, reachable)

    def _register(self, ids: Iterable[str | None], target: LegiTarget):
        for id in ids:
            if id:
                self._by_id.setdefault(id, target)

    def resolve(self, raw: RawLegiLink) -> ResolvedLegiLink:
        target = self._by_id.get(raw["legi_id"])
        return {
            **raw,
            "kind": target.kind if target else None,
            "cid": target.cid if target else None,
            "num": target.num if target else None,
            "chunk_id": target.chunk_id if target else None,
            "canonical_url": target.canonical_url if target else None,
        }

    def resolve_all(self, raws: Iterable[RawLegiLink]) -> list[ResolvedLegiLink]:
        """Resolve and deduplicate (on the resolved cid, else the raw id):
        the first occurrence is kept."""
        links: list[ResolvedLegiLink] = []
        seen: set[str] = set()
        for raw in raws:
            link = self.resolve(raw)
            key = link["cid"] or link["legi_id"]
            if key not in seen:
                seen.add(key)
                links.append(link)
        return links
