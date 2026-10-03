import numpy as np
from sentence_transformers import SentenceTransformer
import faiss
from typing import List, Tuple

class SemanticMemoryEngine:
    """FAISS-powered semantic search for memories (scalable to millions)."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
        self.dimension = 384  # Model output dimension
        self.index = faiss.IndexFlatL2(self.dimension)
        self.memory_ids = []
        
    def add_memory(self, memory_id: int, content: str):
        """Add memory to FAISS index."""
        embedding = self.model.encode([content])[0]
        self.index.add(np.array([embedding], dtype=np.float32))
        self.memory_ids.append(memory_id)
        
    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        """Semantic search for relevant memories."""
        query_embedding = self.model.encode([query])[0]
        distances, indices = self.index.search(
            np.array([query_embedding], dtype=np.float32), 
            top_k
        )
        
        results = [
            (self.memory_ids[idx], float(1 / (1 + dist)))  # Convert distance to similarity
            for idx, dist in zip(indices[0], distances[0])
        ]
        return results
    
    def save_index(self, path: str = "models/faiss_index.bin"):
        """Persist FAISS index to disk."""
        faiss.write_index(self.index, path)
        
    def load_index(self, path: str = "models/faiss_index.bin"):
        """Load FAISS index from disk."""
        self.index = faiss.read_index(path)
