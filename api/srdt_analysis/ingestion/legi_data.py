import json
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from dotenv import load_dotenv

from srdt_analysis.clients.collections import AlbertCollectionHandler
from srdt_analysis.clients.elastic_handler import ElasticIndicesHandler
from srdt_analysis.core.constants import CHUNK_INDEX
from srdt_analysis.core.models import (
    Chunk,
    DocumentData,
    LegiKind,
    LegiLink,
    RawLegiLink,
)
from srdt_analysis.ingestion.data_exploiter_embed import make_batches
from srdt_analysis.text.chunker import Chunker

uri = "https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006072050"

articles_uri = "https://www.legifrance.gouv.fr/codes/article_lc"

chunker = Chunker()

load_dotenv()
albert = AlbertCollectionHandler()

elastic = ElasticIndicesHandler()


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


def recursive_lookup(path, node) -> list[DocumentData]:
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
            {
                "articles": articles,
                # todo
                "cdtn_id": data["cid"],
                "initial_id": data["cid"],
                "title": " ".join(newPath),
                "content": text,
                "content_chunked": chunker.split_character_recursive(text),
                "url": f"{uri}/{data['cid']}",
                "source": "code_du_travail",
                "idcc": None,
            }
        ]

    else:
        docs = []
        for c in node["children"]:
            docs = docs + recursive_lookup(newPath, c)
        return docs


def load_legi_code() -> dict:
    with open(str(os.getenv("LEGI_DATA_PATH"))) as f:
        return json.load(f)


def get_legi_data(code: Optional[dict] = None) -> list[DocumentData]:
    return recursive_lookup([], code if code is not None else load_legi_code())


def get_legi_data_chunked(code: Optional[dict] = None) -> list[Chunk]:
    docs = get_legi_data(code)

    chunk_list: list[Chunk] = []

    for doc in docs:
        for idx, ds in enumerate(doc["content_chunked"]):
            chunk_list.append(
                {
                    "content": ds.page_content,
                    "id": doc["cdtn_id"],
                    "embedding": None,
                    "metadata": {
                        "articles": doc["articles"],
                        "idx": idx,
                        "id": doc["cdtn_id"],
                        "initial_id": doc["initial_id"],
                        "url": doc["url"],
                        "source": doc["source"],
                        "title": doc["title"],
                        "idcc": None,
                    },
                }
            )

    # run batches of 64 chunks to get embeddings
    batches = make_batches(chunk_list, 64)

    for docs in batches:
        contents = [doc["content"] for doc in docs]
        embeddings = albert.embeddings(contents)

        for doc, emb in zip(docs, embeddings):
            doc["embedding"] = emb  # type: ignore

    return chunk_list


def get_article_url(num: str) -> Optional[str]:
    node = elastic.get_article_node(CHUNK_INDEX, num)

    if len(node) < 1 or node[0]["metadata"]["articles"] is None:
        return None

    else:
        res = list(filter(lambda a: a["num"] == num, node[0]["metadata"]["articles"]))
        return res[0]["url"]


@dataclass
class LegiTarget:
    kind: LegiKind
    cid: str
    num: Optional[str]
    # cdtn_id of the code du travail chunk containing the article / section
    chunk_id: Optional[str]
    canonical_url: str


class LegiIndex:
    """Resolve LEGIARTI/LEGISCTA ids (including old article versions) against
    the indexed code du travail.
    """

    def __init__(self, code: dict):
        self._by_id: dict[str, LegiTarget] = {}
        self._walk(code, chunk_id=None, reachable=True)

    def _walk(self, node, chunk_id: Optional[str], reachable: bool):
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

    def _register(self, ids: Iterable[Optional[str]], target: LegiTarget):
        for id in ids:
            if id:
                self._by_id.setdefault(id, target)

    def resolve(self, raw: RawLegiLink) -> LegiLink:
        target = self._by_id.get(raw["legi_id"])
        return {
            **raw,
            "kind": target.kind if target else None,
            "cid": target.cid if target else None,
            "num": target.num if target else None,
            "chunk_id": target.chunk_id if target else None,
            "canonical_url": target.canonical_url if target else None,
        }

    def resolve_all(self, raws: Iterable[RawLegiLink]) -> list[LegiLink]:
        """Resolve and deduplicate (on the resolved cid, else the raw id):
        the first occurrence is kept."""
        links: list[LegiLink] = []
        seen: set[str] = set()
        for raw in raws:
            link = self.resolve(raw)
            key = link["cid"] or link["legi_id"]
            if key not in seen:
                seen.add(key)
                links.append(link)
        return links
