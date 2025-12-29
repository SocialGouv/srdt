import json
import os

from dotenv import load_dotenv

from srdt_analysis.chunker import Chunker
from srdt_analysis.collections import AlbertCollectionHandler
from srdt_analysis.data_exploiter_embed import make_batches
from srdt_analysis.models import Chunk, DocumentData

uri = "https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006072050"
chunker = Chunker()

load_dotenv()
albert = AlbertCollectionHandler()


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


def recursive_lookup(path, node) -> list[DocumentData]:
    data = node["data"]

    if "title" not in data:
        return []

    title = data["title"]

    newPath = path + [title]

    if len(node["children"]) < 1:
        return []

    # if any of its children is an article, we flatten them and select the node
    elif next(c["type"] == "article" for c in node["children"]):
        text = " \n ".join(get_text_flat(node))
        return [
            {
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


def get_legi_data() -> list[DocumentData]:
    with open(str(os.getenv("LEGI_DATA_PATH"))) as f:
        code = json.load(f)
        return recursive_lookup([], code)


def get_legi_data_chunked() -> list[Chunk]:
    docs = get_legi_data()

    chunk_list: list[Chunk] = []

    for doc in docs:
        for idx, ds in enumerate(doc["content_chunked"]):
            chunk_list.append(
                {
                    "content": ds.page_content,
                    "id": doc["cdtn_id"],
                    "embedding": None,
                    "metadata": {
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
