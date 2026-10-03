"""WebSocket connection manager - NO decorators here."""
from typing import Dict, List
from fastapi import WebSocket
import json

class ConnectionManager:
    """Manages WebSocket connections."""
    
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        print(f"✅ WebSocket connected: {user_id}")
    
    def disconnect(self, websocket: WebSocket, user_id: str):
        """Remove a WebSocket connection."""
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        print(f"❌ WebSocket disconnected: {user_id}")
    
    async def send_personal_message(self, message: dict, user_id: str):
        """Send message to a specific user."""
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                await connection.send_json(message)
    
    async def broadcast(self, message: dict):
        """Send message to all connected users."""
        for user_connections in self.active_connections.values():
            for connection in user_connections:
                await connection.send_json(message)

# Global instance
manager = ConnectionManager()
