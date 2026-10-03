import httpx

BASE_URL = "http://127.0.0.1:8000"

def health_check() -> dict:
    """Check if API is running"""
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"status": "error", "detail": str(e)}

def send_message(message: str, session_id: str = "default") -> dict:
    """Send chat message to backend"""
    try:
        response = httpx.post(
            f"{BASE_URL}/chat",
            json={
                "query": message,  # ← Changed from "message" to "query"
                "session_id": session_id
            },
            timeout=300
        )
        
        response.raise_for_status()
        data = response.json()
        
        if "response" not in data:
            return {"response": "⚠️ Backend returned invalid format"}
        
        return data
        
    except httpx.HTTPStatusError as e:
        return {"response": f"HTTP {e.response.status_code}: {e.response.text}"}
    
    except httpx.RequestError as e:
        return {"response": f"Connection failed: {str(e)}"}
    
    except ValueError as e:
        return {"response": f"JSON parse error: {str(e)}"}
    
    except Exception as e:
        return {"response": f"Error: {str(e)}"}

def get_memories(session_id: str = "default") -> list:
    """Get conversation history"""
    try:
        response = httpx.get(f"{BASE_URL}/memory", timeout=10)
        memories = response.json()
        return [{"role": "assistant", "content": m.get("content", "")} for m in memories]
    except:
        return []

def clear_memory(session_id: str = "default") -> dict:
    """Clear conversation history"""
    try:
        response = httpx.delete(f"{BASE_URL}/memory/{session_id}", timeout=10)
        return response.json()
    except Exception as e:
        return {"status": "error", "detail": str(e)}

