import os
from typing import List, cast

import pandas as pd
from dotenv import load_dotenv

from srdt_analysis.api.schemas import ChunkResult, ContentResult

load_dotenv()

docs = pd.read_parquet(cast(str, os.getenv("DOCS_PARQUET")))
chunks = pd.read_parquet(cast(str, os.getenv("CHUNKS_PARQUET")))


def getChunksByIdcc(idcc: str) -> List[ChunkResult]:
    idcc_chunks = chunks[chunks["idcc"] == idcc][["metadata", "content", "id_chunk"]]
    idcc_chunks["score"] = 1
    records = idcc_chunks.to_dict("records")  # type: ignore
    for r in records:
        r["metadata"]["id"] = r["metadata"]["document_id"]
    return cast(List[ChunkResult], records)


def getDocsContent(ids: List[str]) -> List[ContentResult]:
    matches = docs[docs["cdtn_id"].isin(ids)]
    records = matches.apply(
        lambda row: (
            {
                "metadata": {
                    "document_id": row["cdtn_id"],
                    "title": row["title"],
                    "source": row["source"],
                    "url": row["url"],
                    "idcc": row["idcc"],
                    "id": row["cdtn_id"],
                },
                "content": " \n ".join(row["content_chunked"]),
            }
        ),
        axis=1,
    )
    record_dict = dict(zip(matches["cdtn_id"], records.to_list()))

    return [record_dict[id] for id in ids]  # type: ignore
