import redis
import json
from typing import Optional, Any
from functools import wraps
import os

class RedisCache:
    """High-performance caching with Redis."""
    
    def __init__(self, host: str = None, port: int = 6379):
        # Support Docker environment
        if host is None:
            host = os.getenv("REDIS_HOST", "localhost")
        
        try:
            self.client = redis.Redis(host=host, port=port, decode_responses=True)
            self.client.ping()  # Test connection
            self.available = True
        except redis.ConnectionError:
            print("⚠️ Redis not available - caching disabled")
            self.available = False
            self.client = None
        
    def cache_result(self, key: str, ttl: int = 300):
        """Decorator for caching function results."""
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Skip if Redis unavailable
                if not self.available:
                    return await func(*args, **kwargs)
                
                # Check cache
                cached = self.client.get(key)
                if cached:
                    return json.loads(cached)
                
                # Execute function
                result = await func(*args, **kwargs)
                
                # Store in cache
                self.client.setex(key, ttl, json.dumps(result))
                return result
            return wrapper
        return decorator
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if not self.available:
            return None
        cached = self.client.get(key)
        return json.loads(cached) if cached else None
    
    def set(self, key: str, value: Any, ttl: int = 300):
        """Set value in cache."""
        if self.available:
            self.client.setex(key, ttl, json.dumps(value))
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate all keys matching pattern."""
        if not self.available:
            return
        keys = self.client.keys(pattern)
        if keys:
            self.client.delete(*keys)

# Global cache instance
cache = RedisCache()
