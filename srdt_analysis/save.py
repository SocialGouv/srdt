import pandas as pd
from typing import List, Dict


class DocumentProcessor:
    def __init__(self, data_folder: str = "data"):
        self.data_folder = data_folder

    def save_to_csv(self, data: List[Dict], filename: str) -> None:
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
        vector_summary: dict,
        vector_keywords: dict,
        idcc: str = "0000",
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
