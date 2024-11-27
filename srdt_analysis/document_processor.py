from typing import List

import pandas as pd

from srdt_analysis.models import DocumentData, SplitDocument


class DocumentProcessor:
    def __init__(self, data_folder: str = "data"):
        self.data_folder = data_folder

    def save_to_csv(self, data: List[DocumentData], filename: str) -> None:
        df = pd.DataFrame(data)
        df.to_csv(f"{self.data_folder}/{filename}", index=False)

    def process_document(
        self,
        cdtn_id: str,
        initial_id: str,
        title: str,
        content: str,
        keywords: str,
        summary: str,
        questions: str,
        content_chunked: List[SplitDocument],
        idcc: str,
        url: str,
    ) -> DocumentData:
        return {
            "cdtn_id": cdtn_id,
            "initial_id": initial_id,
            "title": title,
            "content": content,
            "keywords": keywords,
            "summary": summary,
            "questions": questions,
            "idcc": idcc,
            "content_chunked": content_chunked,
            "url": url,
        }
