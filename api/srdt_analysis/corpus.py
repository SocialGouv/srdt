import os
from typing import List, cast

import pandas as pd
from dotenv import load_dotenv

from srdt_analysis.api.schemas import ChunkResult

load_dotenv()

docs = pd.read_parquet(cast(str, os.getenv("DOCS_PARQUET")))
chunks = pd.read_parquet(cast(str, os.getenv("CHUNKS_PARQUET")))


def getChunksByIdcc(idcc: str) -> List[ChunkResult]:
    idcc_chunks = chunks[chunks["idcc"] == idcc][["metadata", "content", "id_chunk"]]
    idcc_chunks["score"] = 1
    return cast(List[ChunkResult], idcc_chunks.to_dict("records"))
