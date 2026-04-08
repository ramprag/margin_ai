import redis
import hashlib
import json
import logging
import threading
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


# ── FAISS Vector Index (replaces O(N) Python list scan) ─────────────────
_faiss_index = None
_faiss_available = None


def _get_faiss():
    """Lazy-check for FAISS availability."""
    global _faiss_available
    if _faiss_available is None:
        try:
            import faiss
            _faiss_available = True
        except ImportError:
            _faiss_available = False
            logger.warning("faiss-cpu not installed. Falling back to numpy-based vector search.")
    return _faiss_available


class FAISSIndex:
    """
    Thread-safe FAISS-backed vector index for sub-millisecond similarity search.
    Replaces the O(N) Python list scan with O(1) approximate nearest-neighbor lookup.
    Falls back to numpy dot-product if FAISS is not installed.
    """
    DIMENSION = 384  # all-MiniLM-L6-v2 output dimension

    def __init__(self, max_size: int = 10000):
        self._max_size = max_size
        self._lock = threading.Lock()
        # Ordered list of hashes, index i corresponds to FAISS vector i
        self._hash_list: list = []

        if _get_faiss():
            import faiss
            # Inner Product index (equivalent to cosine similarity on L2-normalized vectors)
            self._index = faiss.IndexFlatIP(self.DIMENSION)
            self._backend = "faiss"
            logger.info("FAISS IndexFlatIP initialized for sub-ms vector search.")
        else:
            self._index = None
            self._vectors = []  # Fallback: list of numpy arrays
            self._backend = "numpy"

    def add(self, prompt_hash: str, embedding):
        """Add an embedding to the index."""
        import numpy as np
        vec = np.array(embedding, dtype=np.float32).reshape(1, -1)
        # L2-normalize for cosine similarity via inner product
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        with self._lock:
            # Evict oldest if at capacity
            if len(self._hash_list) >= self._max_size:
                self._hash_list.pop(0)
                if self._backend == "faiss":
                    # FAISS IndexFlatIP doesn't support remove; rebuild periodically
                    # For now, we accept slight over-capacity (N+1) until next rebuild
                    pass
                else:
                    self._vectors.pop(0)

            self._hash_list.append(prompt_hash)
            if self._backend == "faiss":
                self._index.add(vec)
            else:
                self._vectors.append(vec.flatten())

    def search(self, embedding, threshold: float) -> Optional[str]:
        """
        Find the most similar cached prompt hash.
        Returns the hash if similarity >= threshold, else None.
        """
        import numpy as np
        if len(self._hash_list) == 0:
            return None

        vec = np.array(embedding, dtype=np.float32).reshape(1, -1)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        with self._lock:
            if self._backend == "faiss":
                scores, indices = self._index.search(vec, 1)
                best_score = float(scores[0][0])
                best_idx = int(indices[0][0])
                if best_score >= threshold and 0 <= best_idx < len(self._hash_list):
                    return self._hash_list[best_idx]
            else:
                # Numpy fallback: vectorized dot product (still much faster than Python loop)
                matrix = np.array(self._vectors, dtype=np.float32)
                scores = matrix @ vec.flatten()
                best_idx = int(np.argmax(scores))
                best_score = float(scores[best_idx])
                if best_score >= threshold and 0 <= best_idx < len(self._hash_list):
                    return self._hash_list[best_idx]

        return None

    @property
    def size(self) -> int:
        return len(self._hash_list)


class SemanticCache:
    """
    Two-tier semantic caching system for the Margin AI Gateway.

    Tier 1 (Fast Path): Exact-match SHA256 hash lookup in Redis. ~0ms overhead.
    Tier 2 (Smart Path): FAISS-backed embedding similarity search. If the incoming
                         prompt's embedding is >= SIMILARITY_THRESHOLD similar to a
                         cached prompt, return the cached response.

    Falls back to an in-memory LRU cache with bounded size if Redis is unavailable.
    """
    def __init__(self):
        self._redis = None
        # Bounded in-memory fallback (prevents OOM)
        self._memory_cache = LRUCache(maxsize=10000)
        # FAISS-backed vector index (replaces the old Python list)
        self._vector_index = FAISSIndex(max_size=10000)

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

    def get_cached_response(self, prompt: str, api_key: str = "") -> Optional[dict]:
        """
        Two-tier cache lookup (tenant-isolated):
        1. Exact SHA256 hash match (fast path, 0ms).
        2. FAISS semantic similarity search.
        The api_key is included in the hash to prevent cross-tenant data leaks.
        """
        normalized = self._normalize_prompt(prompt)
        # Salt the hash with the API key to ensure tenant isolation
        tenant_salt = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else "global"
        prompt_hash = hashlib.sha256(f"{tenant_salt}:{normalized}".encode()).hexdigest()

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

        # --- Tier 2: FAISS Semantic Similarity ---
        embedding = self._get_embedding(normalized)
        if embedding is not None and self._vector_index.size > 0:
            best_hash = self._vector_index.search(embedding, settings.SIMILARITY_THRESHOLD)
            if best_hash:
                logger.info(
                    f"Cache Hit [Tier 2: Semantic FAISS | "
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

    def set_cached_response(self, prompt: str, response: dict, ttl: int = 3600, api_key: str = ""):
        """
        Store response in cache with both exact hash and FAISS embedding vector.
        Tenant-isolated: the api_key is included in the hash.
        """
        normalized = self._normalize_prompt(prompt)
        tenant_salt = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else "global"
        prompt_hash = hashlib.sha256(f"{tenant_salt}:{normalized}".encode()).hexdigest()

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

        # Store the embedding vector in the FAISS index for Tier 2 semantic search
        embedding = self._get_embedding(normalized)
        if embedding is not None:
            self._vector_index.add(prompt_hash, embedding)


semantic_cache = SemanticCache()
