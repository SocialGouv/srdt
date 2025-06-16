import os
from typing import List
from dotenv import load_dotenv
import pandas as pd

from srdt_analysis.api.schemas import ChunkResult

load_dotenv()

docs = pd.read_parquet(os.getenv("DOCS_PARQUET"))
chunks = pd.read_parquet(os.getenv("CHUNKS_PARQUET"))


def getChunksByIdcc(idcc: str) -> List[ChunkResult]:
    ids = docs[docs["idcc"] == idcc]["cdtn_id"]
    idcc_chunks = chunks[chunks["cdtn_id"].isin(ids)][
        ["metadata", "content", "id_chunk"]
    ]
    idcc_chunks["score"] = 1
    return idcc_chunks.to_dict("records")
