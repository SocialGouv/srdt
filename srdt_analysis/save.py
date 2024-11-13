import csv
from typing import List, Dict


def save_to_csv(data: List[Dict], filename: str) -> None:
    headers = [
        "cdtn_id",
        "initial_id",
        "title",
        "content",
        "idcc",
        "keywords",
        "summary",
        "vector_summary",
        "vector_keywords",
    ]

    with open(f"data/{filename}", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(data)


def remove_newlines(content: str) -> str:
    return content.replace("\n", "-")


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
        "content": remove_newlines(content),
        "keywords": remove_newlines(keywords),
        "summary": remove_newlines(summary),
        "vector_summary": remove_newlines(str(vector_summary)),
        "vector_keywords": remove_newlines(str(vector_keywords)),
        "idcc": idcc,
    }
