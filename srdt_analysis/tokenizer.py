import os

from transformers import AutoTokenizer

from srdt_analysis.constants import LLM_MODEL


class Tokenizer:
    def __init__(self, hf_token: str | None = None):
        token = hf_token or os.getenv("HF_API_TOKEN")
        if not token:
            raise ValueError("HF_API_TOKEN not provided or found in environment")

        self._tokenizer = AutoTokenizer.from_pretrained(LLM_MODEL, token=token)

    def compute_nb_tokens(self, text: str) -> int:
        tokens = self._tokenizer.encode(text)
        return len(tokens)
