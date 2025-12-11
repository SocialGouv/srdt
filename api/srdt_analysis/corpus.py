import os
from typing import List, cast

import pandas as pd
from dotenv import load_dotenv

from srdt_analysis.api.schemas import ChunkResult, ContentResult
from srdt_analysis.elastic_handler import ElasticIndicesHandler

load_dotenv()

docs = pd.read_parquet(cast(str, os.getenv("DOCS_PARQUET")))
chunks = pd.read_parquet(cast(str, os.getenv("CHUNKS_PARQUET")))

es_handler = ElasticIndicesHandler()


def getDocs():
    return docs


def getChunksByIdcc(idcc: str, score: int = 1) -> List[ChunkResult]:
    hits = es_handler.get_idcc(idcc)

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


def getDocsContent(ids: List[str]) -> List[ContentResult]:
    hits = es_handler.get_chunks(ids)

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
