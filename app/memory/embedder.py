from sentence_transformers import SentenceTransformer
import numpy as np
import os

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

_model = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model

def embed_text(text: str) -> np.ndarray:
    """
    Returns a normalized float32 embedding vector.
    Shape: (384,) for all-MiniLM-L6-v2
    """
    model = get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.astype(np.float32)

def embed_batch(texts: list[str]) -> np.ndarray:
    """
    Batch embed for efficiency.
    Shape: (N, 384)
    """
    model = get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return embeddings.astype(np.float32)
