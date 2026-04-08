import redis
import hashlib
import json
import logging
from typing import Optional
from cachetools import LRUCache
from backend.config import settings

logger = logging.getLogger(__name__)

# Lazy-loaded sentence transformer model (loaded on first cache call, not at import)
_embedding_model = None


def _get_embedding_model():
    """Lazy-load the sentence-transformers model to keep gateway startup fast."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Sentence-transformer model 'all-MiniLM-L6-v2' loaded for semantic caching.")
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. Falling back to exact-match caching. "
                "Install with: pip install sentence-transformers"
            )
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}. Falling back to exact-match.")
    return _embedding_model


def _cosine_similarity(vec_a, vec_b) -> float:
    """Compute cosine similarity between two vectors without importing numpy at module level."""
    import numpy as np
    dot = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class SemanticCache:
    """
    Two-tier semantic caching system for the Margin AI Gateway.

    Tier 1 (Fast Path): Exact-match SHA256 hash lookup in Redis. ~0ms overhead.
    Tier 2 (Smart Path): Embedding-based cosine similarity search. If the incoming
                         prompt's embedding is >= SIMILARITY_THRESHOLD similar to a 
                         cached prompt, return the cached response.

    Falls back to an in-memory LRU cache with bounded size if Redis is unavailable.
    """
    def __init__(self):
        self._redis = None
        # Bounded in-memory fallback (prevents OOM)
        self._memory_cache = LRUCache(maxsize=10000)
        # In-memory vector index for semantic search (list of (hash, embedding) tuples)
        self._vector_index = []

    @property
    def redis(self):
        if self._redis is None:
            try:
                self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
                self._redis.ping()
                logger.info("Redis connected for semantic caching.")
            except Exception as e:
                logger.warning(f"Redis unavailable: {e}. Falling back to in-memory LRU cache.")
                self._redis = False  # Mark as failed to prevent retries
        return self._redis if self._redis else None

    def _normalize_prompt(self, prompt: str) -> str:
        """Normalize whitespace and case for exact-match hashing."""
        return " ".join(prompt.lower().split())

    def _get_embedding(self, text: str):
        """Generate embedding vector for the given text. Returns None if model unavailable."""
        model = _get_embedding_model()
        if model is None:
            return None
        try:
            return model.encode(text, convert_to_numpy=True)
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            return None

    def get_cached_response(self, prompt: str) -> Optional[dict]:
        """
        Two-tier cache lookup:
        1. Exact SHA256 hash match (fast path, 0ms).
        2. Semantic similarity search against stored embeddings.
        """
        normalized = self._normalize_prompt(prompt)
        prompt_hash = hashlib.sha256(normalized.encode()).hexdigest()

        # --- Tier 1: Exact Match ---
        # Try Redis first
        if self.redis:
            try:
                cached_data = self.redis.get(f"cache:{prompt_hash}")
                if cached_data:
                    logger.info("Cache Hit [Tier 1: Exact Match - Redis]")
                    return json.loads(cached_data)
            except Exception:
                pass

        # Try in-memory fallback
        if prompt_hash in self._memory_cache:
            logger.info("Cache Hit [Tier 1: Exact Match - Memory]")
            return self._memory_cache[prompt_hash]

        # --- Tier 2: Semantic Similarity ---
        embedding = self._get_embedding(normalized)
        if embedding is not None and len(self._vector_index) > 0:
            best_hash = None
            best_score = 0.0

            for stored_hash, stored_embedding in self._vector_index:
                score = _cosine_similarity(embedding, stored_embedding)
                if score > best_score:
                    best_score = score
                    best_hash = stored_hash

            if best_score >= settings.SIMILARITY_THRESHOLD and best_hash:
                logger.info(
                    f"Cache Hit [Tier 2: Semantic | similarity={best_score:.4f} "
                    f"threshold={settings.SIMILARITY_THRESHOLD}]"
                )
                # Retrieve the response for the best-matching hash
                if self.redis:
                    try:
                        cached_data = self.redis.get(f"cache:{best_hash}")
                        if cached_data:
                            return json.loads(cached_data)
                    except Exception:
                        pass
                if best_hash in self._memory_cache:
                    return self._memory_cache[best_hash]

        return None

    def set_cached_response(self, prompt: str, response: dict, ttl: int = 3600):
        """
        Store response in cache with both exact hash and embedding vector.
        """
        normalized = self._normalize_prompt(prompt)
        prompt_hash = hashlib.sha256(normalized.encode()).hexdigest()

        # Store the response data
        # 1. Try Redis
        if self.redis:
            try:
                self.redis.setex(f"cache:{prompt_hash}", ttl, json.dumps(response))
            except Exception:
                # Fall through to memory
                self._memory_cache[prompt_hash] = response
        else:
            # 2. Fallback to bounded LRU memory cache
            self._memory_cache[prompt_hash] = response

        # Store the embedding vector for Tier 2 semantic search
        embedding = self._get_embedding(normalized)
        if embedding is not None:
            # Cap vector index size to prevent unbounded memory growth
            if len(self._vector_index) >= 10000:
                self._vector_index.pop(0)  # Remove oldest entry
            self._vector_index.append((prompt_hash, embedding))


semantic_cache = SemanticCache()
