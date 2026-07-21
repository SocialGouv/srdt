import json
import os

from bs4 import BeautifulSoup
from dotenv import load_dotenv

from srdt_analysis.clients.collections import AlbertCollectionHandler
from srdt_analysis.core.models import Chunk
from srdt_analysis.ingestion.data_exploiter_embed import make_batches
from srdt_analysis.text.chunker import Chunker
from srdt_analysis.text.tokenizer import Tokenizer

load_dotenv()

# TODO remove this
DATA_DIR = "/Users/remi/dev/socialgouv/kali-data/data/"

CC_MAIN_PARTS = ("Texte de base", "Textes Attachés", "Textes Salaires")

conventions_uri = "https://www.legifrance.gouv.fr/conv_coll/id"

_tokenizer = Tokenizer()
_chunker = Chunker()
_albert = AlbertCollectionHandler()


def _find_main_part(children, prefix):
    return next(
        (c for c in children if c.get("data", {}).get("title", "").startswith(prefix)),
        None,
    )


def _subtree_height(node):
    children = node.get("children", [])
    if not children:
        return 1
    return 1 + max(_subtree_height(child) for child in children)


def _get_text_content(node):
    content = node.get("data", {}).get("content")
    parts = (
        [BeautifulSoup(content, "html.parser").get_text(separator=" ")]
        if content
        else []
    )
    for child in node.get("children", []):
        parts.append(_get_text_content(child))
    return " ".join(parts)


def parse_cc(data):
    children = data.get("children", [])
    if not children:
        # print('n/a')
        return None

    title = data.get("data", {}).get("title")
    print(title)

    stats = {}
    for part_name in CC_MAIN_PARTS:
        part_node = _find_main_part(children, part_name)
        part_children = part_node.get("children", []) if part_node else []
        n = len(part_children)
        depths = [_subtree_height(c) for c in part_children]
        token_counts = [
            _tokenizer.compute_nb_tokens(_get_text_content(c)) for c in part_children
        ]
        stats[part_name] = {
            "child_count": n,
            "avg_depth": sum(depths) / n if n else 0,
            "min_depth": min(depths) if n else 0,
            "max_depth": max(depths) if n else 0,
            "avg_token_count": sum(token_counts) / n if n else 0,
            "min_token_count": min(token_counts) if n else 0,
            "max_token_count": max(token_counts) if n else 0,
        }

    print(stats, "\n\n\n")
    return (title, stats)


def _walk_articles(node, breadcrumb):
    if node.get("type") == "article":
        yield (breadcrumb, node)
        return
    title = node.get("data", {}).get("title")
    child_breadcrumb = breadcrumb + [title] if title else breadcrumb
    for child in node.get("children", []):
        yield from _walk_articles(child, child_breadcrumb)


def chunk_cc(data):
    children = data.get("children", [])

    chunks = []

    for part in ["Texte de base", "Textes Attachés"]:
        part_node = _find_main_part(children, part)

        if not part_node:
            return []

        idcc = data.get("data", {}).get("num")

        for part_child in part_node.get("children", []):
            for breadcrumb, article in _walk_articles(part_child, [part]):
                content = article.get("data", {}).get("content")
                if not content or not BeautifulSoup(content, "html.parser").get_text(
                    strip=True
                ):
                    continue

                article_num = article.get("data", {}).get("num")

                last_breadcrumb = breadcrumb[len(breadcrumb) - 1]
                suffix = f" — Article {article_num}" if article_num else ""

                header = " > ".join(breadcrumb) + suffix
                title = last_breadcrumb + suffix

                # state =  article.get("data", {}).get("etat")
                # if state != 'VIGUEUR_ETEN':
                # print(header, state)

                # print(title)

                for idx, split in enumerate(_chunker.split_html_contribs(content)):
                    chunks.append(
                        {
                            "title": title,
                            "breadcrumb": breadcrumb,
                            "article_num": article_num,
                            "cid": article.get("data", {}).get("cid"),
                            "id": article.get("data", {}).get("id"),
                            "etat": article.get("data", {}).get("etat"),
                            "idx": idx,
                            "idcc": idcc,
                            "content": f"{header}\n{split.page_content}",
                        }
                    )

    return chunks


def embed_cc_chunks(chunks) -> list[Chunk]:
    chunk_list: list[Chunk] = []

    for chunk in chunks:
        id = chunk["id"] if "id" in chunk else chunk["cid"]
        chunk_list.append(
            {
                "content": chunk["content"],
                "id": id,
                "embedding": None,
                "metadata": {
                    "id": id,
                    "source": "conventions",
                    "url": f"{conventions_uri}/{id}",
                    "initial_id": id,
                    "title": chunk["title"],
                    # 'breadcrumb': chunk['breadcrumb'],
                    # 'article_num': chunk['article_num'],
                    "idx": chunk["idx"],
                    "idcc": str(chunk["idcc"]),
                    "articles": [],
                },
            }
        )

    for batch in make_batches(chunk_list, 64):
        contents = [c["content"] for c in batch]
        embeddings = _albert.embeddings(contents)
        for c, emb in zip(batch, embeddings):
            c["embedding"] = emb  # type: ignore

    return chunk_list


def parse_all_agreements(data_dir=DATA_DIR):
    for filename in os.listdir(data_dir):
        if not filename.endswith(".json") or filename == "index.json":
            continue
        with open(os.path.join(data_dir, filename)) as f:
            data = json.load(f)
        res = chunk_cc(data)

        # print(json.dumps(res[:4]))

        if len(res) > 0:
            break
    #     if res :
    #         (title, stats) = res
    #         stats['Texte de base']['title'] = title
    #         aggregated.append(stats['Texte de base'])
    # pd.DataFrame(aggregated).to_csv("~/tmp/ccs.csv")


def get_conventions_chunked(data_dir=DATA_DIR):
    aggregated = []
    for filename in os.listdir(data_dir):
        # if not filename.endswith('5635657.json') or filename == 'index.json':
        if not filename.endswith(".json") or filename.startswith("index"):
            continue
        print(filename)
        with open(os.path.join(data_dir, filename)) as f:
            data = json.load(f)
        res = chunk_cc(data)

        # print(json.dumps(res[:4]))

        with_embeddings = embed_cc_chunks(res)

        aggregated.extend(with_embeddings)

        # if len(res) > 0:
        #     break

    return aggregated
