import redis
import hashlib
import json
from backend.config import settings

class SemanticCache:
    """
    Sub-ms caching using Redis for recurring queries.
    Uses prompt SHA256 hashes + basic text normalization.
    """
    def __init__(self):
        self._redis = None

    @property
    def redis(self):
        if self._redis is None:
            import redis
            try:
                self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
                # Test connection
                self._redis.ping()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Redis connection failed: {e}")
                return None
        return self._redis

    def _normalize_prompt(self, prompt: str) -> str:
        """
        Removes whitespace and lowercases to avoid cache misses on small changes.
        """
        return " ".join(prompt.lower().split())

    def get_cached_response(self, prompt: str) -> dict:
        """
        Retrieves a cached JSON response if it exists.
        """
        if not self.redis:
            return None
            
        normalized_prompt = self._normalize_prompt(prompt)
        prompt_hash = hashlib.sha256(normalized_prompt.encode()).hexdigest()
        
        try:
            cached_data = self.redis.get(f"cache:{prompt_hash}")
            if cached_data:
                return json.loads(cached_data)
        except Exception:
            pass
        return None

    def set_cached_response(self, prompt: str, response: dict, ttl: int = 3600):
        """
        Sets a new cache entry for a given prompt. Default TTL: 1 hour.
        """
        if not self.redis:
            return
            
        normalized_prompt = self._normalize_prompt(prompt)
        prompt_hash = hashlib.sha256(normalized_prompt.encode()).hexdigest()
        
        try:
            self.redis.setex(f"cache:{prompt_hash}", ttl, json.dumps(response))
        except Exception:
            pass

semantic_cache = SemanticCache()
