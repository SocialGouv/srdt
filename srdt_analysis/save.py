import pandas as pd
from typing import List, Dict


def save_to_csv(data: List[Dict], filename: str) -> None:
    df = pd.DataFrame(data)
    df.to_csv(f"data/{filename}", index=False)


def process_document(
    cdtn_id: str,
    initial_id: str,
    title: str,
    content: str,
    keywords: str,
    summary: str,
    vector_summary: dict,
    vector_keywords: dict,
    idcc="0000",
) -> Dict:
    return {
        "cdtn_id": cdtn_id,
        "initial_id": initial_id,
        "title": title,
        "content": content,
        "keywords": keywords,
        "summary": summary,
        "vector_summary": vector_summary,
        "vector_keywords": vector_keywords,
        "idcc": idcc,
    }
