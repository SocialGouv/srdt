from FlagEmbedding import BGEM3FlagModel


def generate_vector(text: str) -> dict:
    model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    vector = model.encode(text)
    return vector
