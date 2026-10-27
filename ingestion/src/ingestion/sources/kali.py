"""Collective agreements from the KALI JSON files (@socialgouv/kali-data format),
one chunk group per article (ported from the api's ingestion/agreements.py)."""

from bs4 import BeautifulSoup

from ingestion.contract import Chunk
from ingestion.text.chunker import Chunker

conventions_uri = "https://www.legifrance.gouv.fr/conv_coll/id"


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


def chunk_cc(data, chunker: Chunker) -> list[Chunk]:
    children = data.get("children", [])

    chunks: list[Chunk] = []

    # "Textes Salaires" is left out
    for part in ["Texte de base", "Textes Attachés"]:
        part_node = _find_main_part(children, part)

        if not part_node:
            continue

        idcc = data.get("data", {}).get("num")

        for part_child in part_node.get("children", []):
            for breadcrumb, article in _walk_articles(part_child, [part]):
                article_data = article.get("data", {})
                content = article_data.get("content")
                if not content or not BeautifulSoup(content, "html.parser").get_text(
                    strip=True
                ):
                    continue

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
