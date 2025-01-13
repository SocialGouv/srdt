import os

from transformers import AutoTokenizer


class Tokenizer:
    def __init__(self, model: str):
        if not os.getenv("HF_API_TOKEN"):
            raise ValueError("HF_API_TOKEN not provided or found in environment")
        self._tokenizer = AutoTokenizer.from_pretrained(
            model, token=os.getenv("HF_API_TOKEN")
        )

    def compute_nb_tokens(self, text: str) -> int:
        tokens = self._tokenizer.encode(text)
        return len(tokens)
