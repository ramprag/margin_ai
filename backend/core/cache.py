import redis
import hashlib
import json
from backend.config import settings

class SemanticCache:
    """
    Sub-ms caching using Redis for recurring queries.
    Uses prompt SHA256 hashes + basic text normalization.
    Falls back to an in-memory dictionary if Redis is unavailable.
    """
    def __init__(self):
        self._redis = None
        self._memory_cache = {} # Fallback dictionary

    @property
    def redis(self):
        if self._redis is None:
            import redis
            try:
                self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
                self._redis.ping()
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Redis unavailable. Falling back to in-memory Cache.")
                self._redis = False # Mark as failed to prevent retries
        return self._redis if self._redis else None

    def _normalize_prompt(self, prompt: str) -> str:
        return " ".join(prompt.lower().split())

    def get_cached_response(self, prompt: str) -> dict:
        normalized_prompt = self._normalize_prompt(prompt)
        prompt_hash = hashlib.sha256(normalized_prompt.encode()).hexdigest()
        
        # 1. Try Redis
        if self.redis:
            try:
                cached_data = self.redis.get(f"cache:{prompt_hash}")
                if cached_data:
                    return json.loads(cached_data)
            except Exception:
                pass
                
        # 2. Try Memory Fallback
        if prompt_hash in self._memory_cache:
            return self._memory_cache[prompt_hash]
            
        return None

    def set_cached_response(self, prompt: str, response: dict, ttl: int = 3600):
        normalized_prompt = self._normalize_prompt(prompt)
        prompt_hash = hashlib.sha256(normalized_prompt.encode()).hexdigest()
        
        # 1. Try Redis
        if self.redis:
            try:
                self.redis.setex(f"cache:{prompt_hash}", ttl, json.dumps(response))
                return
            except Exception:
                pass
                
        # 2. Fallback to Memory
        self._memory_cache[prompt_hash] = response

semantic_cache = SemanticCache()
