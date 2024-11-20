from typing import Dict, List

import pandas as pd


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
        questions: str,
        vector_summary: dict,
        vector_keywords: dict,
        vector_questions: dict,
        idcc: str = "0000",
    ) -> Dict:
        return {
            "cdtn_id": cdtn_id,
            "initial_id": initial_id,
            "title": title,
            "content": content,
            "keywords": keywords,
            "summary": summary,
            "questions": questions,
            "vector_summary": vector_summary,
            "vector_keywords": vector_keywords,
            "vector_questions": vector_questions,
            "idcc": idcc,
        }
