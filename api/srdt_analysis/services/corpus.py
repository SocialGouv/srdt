from typing import List, cast

from srdt_analysis.api.schemas import ChunkResult, ContentResult
from srdt_analysis.clients.search_handler import get_search_handler


def idcc_with_contribs(idcc: str) -> bool:
    hits = get_search_handler().get_idcc_contributions(idcc, 1)
    return len(hits) > 0


def get_contributions_chunks_by_idcc(idcc: str, score: int = 1) -> List[ChunkResult]:
    hits = get_search_handler().get_idcc_contributions(idcc, 1000)

    def to_chunk(source):
        metadata = source["metadata"]
        return {
            "content": source["content"],
            "score": score,
            "id_chunk": metadata["id"] + "-" + str(metadata["idx"]),
            "metadata": metadata | {"document_id": metadata["id"]},
        }

    chunks = [to_chunk(source) for source in hits]

    return cast(List[ChunkResult], chunks)


def get_docs_content(ids: List[str]) -> List[ContentResult]:
    hits = get_search_handler().get_chunks(ids)

    doc_chunks = {}

    # group chunks by document id
    for hit in hits:
        id = hit["metadata"]["id"]
        idx = str(hit["metadata"]["idx"])
        if id not in doc_chunks.keys():
            doc_chunks[id] = {}
        doc_chunks[id][idx] = hit

    # merge them
    docs_content = []
    for id, chunks in doc_chunks.items():
        doc = chunks["0"]
        doc["metadata"]["document_id"] = id
        keys = list(chunks.keys())
        keys.sort()
        for idx in keys:
            if idx != "0":
                doc["content"] += " \n " + chunks[idx]["content"]

        docs_content.append(doc)

    return docs_content
