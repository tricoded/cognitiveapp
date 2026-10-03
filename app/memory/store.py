from sqlalchemy.orm import Session
from app.models import Memory
from app.schemas import MemoryCreate
from app.memory.embedder import embed_text
from app.memory.retriever import add_memory, search_similar
from datetime import datetime
import math
import numpy as np
import faiss
from fastapi import HTTPException

def compute_importance_score(access_count: int, created_at: datetime) -> float:
    """
    importance = 0.4 * recency + 0.6 * frequency
    Recency decays over time (days since creation).
    Frequency grows with access count.
    """
    days_old = max((datetime.utcnow() - created_at).days, 0)
    recency = math.exp(-0.1 * days_old)         # exponential decay
    frequency = 1 - math.exp(-0.3 * access_count)  # grows with access

    return round(0.4 * recency + 0.6 * frequency, 4)

def create_memory(db: Session, data: MemoryCreate) -> Memory:
    embedding = embed_text(data.content)

    memory = Memory(
        content=data.content,
        category=data.category,
        importance_score=0.5,
        access_count=0
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)

    faiss_idx = add_memory(embedding, memory.id)
    memory.embedding_index = faiss_idx
    db.commit()
    db.refresh(memory)

    return memory

def retrieve_relevant_memories(db: Session, query: str, top_k: int = 5) -> list[Memory]:
    embedding = embed_text(query)
    results = search_similar(embedding, top_k=top_k)

    memories = []
    for result in results:
        memory = db.query(Memory).filter(Memory.id == result["db_memory_id"]).first()
        if memory:
            memory.access_count += 1
            memory.importance_score = compute_importance_score(
                memory.access_count,
                memory.created_at
            )
            db.commit()
            memories.append(memory)

    return memories

def store_memory(db: Session, content: str, category: str, metadata: dict = None) -> Memory:
    """
    Simple wrapper to store a memory without needing MemoryCreate schema.
    Used for quick storage like user profiles.
    """
    from app.schemas import MemoryCreate
    
    # Create the schema object
    memory_data = MemoryCreate(
        content=content,
        category=category
    )
    
    # Use existing create_memory function
    memory = create_memory(db, memory_data)
    
    # Note: metadata parameter exists but Memory model doesn't have metadata field
    # If you need metadata, add it to your Memory model first
    
    return memory


def delete_memory_by_id(db: Session, memory_id: int):
    """Delete a memory and rebuild the FAISS index."""
    from app.models import Memory
    
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
    
    db.delete(memory)
    db.commit()
    
    remaining_memories = db.query(Memory).all()
    
    global memory_manager  
    
    if remaining_memories:
        embeddings = [np.frombuffer(m.embedding, dtype=np.float32) for m in remaining_memories]
        embeddings_array = np.array(embeddings).astype('float32')
        memory_manager.index = faiss.IndexFlatL2(embeddings_array.shape[1])
        memory_manager.index.add(embeddings_array)
    else:
        memory_manager.index = faiss.IndexFlatL2(384)
    
    return {"message": f"Memory {memory_id} deleted successfully", "remaining_count": len(remaining_memories)}
 
def get_all_memories(db: Session) -> list[Memory]:
    return db.query(Memory).order_by(Memory.importance_score.desc()).all()

