import faiss
import numpy as np
import os
import pickle

FAISS_INDEX_PATH = "faiss_index.bin"
FAISS_MAP_PATH = "faiss_map.pkl"  

EMBEDDING_DIM = 384

_index = None
_id_map: list[int] = []  

def _get_index() -> faiss.IndexFlatIP:
    global _index
    if _index is None:
        if os.path.exists(FAISS_INDEX_PATH):
            _index = faiss.read_index(FAISS_INDEX_PATH)
        else:
            _index = faiss.IndexFlatIP(EMBEDDING_DIM)
    return _index

def _load_map() -> list[int]:
    global _id_map
    if not _id_map and os.path.exists(FAISS_MAP_PATH):
        with open(FAISS_MAP_PATH, "rb") as f:
            _id_map = pickle.load(f)
    return _id_map

def _save():
    faiss.write_index(_get_index(), FAISS_INDEX_PATH)
    with open(FAISS_MAP_PATH, "wb") as f:
        pickle.dump(_id_map, f)

def add_memory(embedding: np.ndarray, db_memory_id: int) -> int:
    """
    Add a single embedding to FAISS.
    Returns the FAISS index position.
    """
    index = _get_index()
    id_map = _load_map()

    vec = embedding.reshape(1, -1)
    index.add(vec)

    faiss_position = index.ntotal - 1
    id_map.append(db_memory_id)
    _save()

    return faiss_position

def search_similar(query_embedding: np.ndarray, top_k: int = 5) -> list[dict]:
    """
    Returns list of {db_memory_id, score} sorted by relevance.
    """
    index = _get_index()
    id_map = _load_map()

    if index.ntotal == 0:
        return []

    top_k = min(top_k, index.ntotal)
    vec = query_embedding.reshape(1, -1)
    scores, indices = index.search(vec, top_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx != -1:
            results.append({
                "db_memory_id": id_map[idx],
                "score": float(score)
            })
    return results
