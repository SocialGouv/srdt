from typing import List

import pandas as pd

from srdt_analysis.models import DocumentData


class DocumentProcessor:
    def __init__(self, data_folder: str = "data"):
        self.data_folder = data_folder

    def save_to_csv(self, data: List[DocumentData], filename: str) -> None:
        df = pd.DataFrame(data)
        df.to_csv(f"{self.data_folder}/{filename}", index=False)
