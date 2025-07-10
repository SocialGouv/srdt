import json
import os

from srdt_analysis.chunker import Chunker
from srdt_analysis.models import DocumentData

uri = "https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006072050"
chunker = Chunker()


def get_text_flat(node):
    content = []
    for c in node["children"]:
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
