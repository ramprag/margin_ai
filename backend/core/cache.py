import json
import logging
import threading
from typing import Optional, Dict, Any
from cachetools import LRUCache
from backend.config import settings

logger = logging.getLogger(__name__)

# Lazy-loaded sentence transformer model
_embedding_model = None


def _get_embedding_model():
    """Lazy-load the sentence-transformers model."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Sentence-transformer model 'all-MiniLM-L6-v2' loaded.")
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}")
    return _embedding_model


# ── FAISS Vector Index (with ID Mapping for Sync) ───────────────────────

class FAISSIndex:
    """
    Enterprise-grade FAISS-backed vector index with ID mapping.
    Uses 'Option B': IndexIDMap to ensure vectors and hashes stay 1:1 synced.
    """
    DIMENSION = 384

    def __init__(self, max_size: int = 10000):
        self._max_size = max_size
        self._lock = threading.Lock()
        
        # Maps FAISS ID (int) -> prompt_hash (str)
        self._id_to_hash: Dict[int, str] = {}
        # Queue of IDs to keep track of oldest entries for removal
        self._id_queue: list = []
        # Monotonically increasing ID counter
        self._next_internal_id = 0

        try:
            import faiss
            import numpy as np
            # Layer 1: The core flat index
            self._sub_index = faiss.IndexFlatIP(self.DIMENSION)
            # Layer 2: ID mapping layer to keep vectors tied to specific IDs
            self._index = faiss.IndexIDMap2(self._sub_index)
            self._backend = "faiss"
            logger.info("FAISS IndexIDMap2 initialized for 1:1 synced vector search.")
        except ImportError:
            self._index = None
            self._vectors: Dict[int, Any] = {}
            self._backend = "numpy"
            logger.warning("faiss-cpu not installed. Falling back to ID-mapped numpy search.")

    def add(self, prompt_hash: str, embedding):
        """Add an embedding with a unique ID to ensure perfect sync."""
        import numpy as np
        vec = np.array(embedding, dtype=np.float32).reshape(1, -1)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        with self._lock:
            # 1. Handle Eviction (Explicit ID removal)
            if len(self._id_queue) >= self._max_size:
                oldest_id = self._id_queue.pop(0)
                if self._backend == "faiss":
                    # Explicitly remove the ID from the index to prevent desync
                    self._index.remove_ids(np.array([oldest_id], dtype=np.int64))
                else:
                    self._vectors.pop(oldest_id, None)
                self._id_to_hash.pop(oldest_id, None)

            # 2. Add New Entry
            new_id = self._next_internal_id
            self._next_internal_id += 1
            
            self._id_queue.append(new_id)
            self._id_to_hash[new_id] = prompt_hash
            
            if self._backend == "faiss":
                self._index.add_with_ids(vec, np.array([new_id], dtype=np.int64))
            else:
                self._vectors[new_id] = vec.flatten()

    def search(self, embedding, threshold: float) -> Optional[str]:
        """
        Sub-ms search using IDs to retrieve the correct hash.
        """
        import numpy as np
        if not self._id_to_hash:
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
                
                # Retrieve using the explicit ID found by FAISS
                if best_score >= threshold and best_idx != -1:
                    return self._id_to_hash.get(best_idx)
            else:
                # Optimized Numpy fallback
                ids = list(self._vectors.keys())
                matrix = np.array([self._vectors[i] for i in ids], dtype=np.float32)
                scores = matrix @ vec.flatten()
                best_idx_in_scores = int(np.argmax(scores))
                best_score = float(scores[best_idx_in_scores])
                
                if best_score >= threshold:
                    best_id = ids[best_idx_in_scores]
                    return self._id_to_hash.get(best_id)

        return None

    @property
    def size(self) -> int:
        return len(self._id_to_hash)


class SemanticCache:
    def __init__(self):
        self._redis = None
        # Thread-safe lock for the memory cache
        self._mem_lock = threading.RLock()
        # Bounded in-memory fallback (prevents OOM)
        self._memory_cache = LRUCache(maxsize=10000)
        # The Fixed Index with explicit ID mapping
        self._vector_index = FAISSIndex(max_size=10000)

    @property
    def redis(self):
        if self._redis is None:
            try:
                self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
                self._redis.ping()
                logger.info("Redis connected for semantic caching.")
            except Exception as e:
                logger.warning(f"Redis unavailable: {e}")
                self._redis = False
        return self._redis if self._redis else None

    def _normalize_prompt(self, prompt: str) -> str:
        return " ".join(prompt.lower().split())

    def _get_embedding(self, text: str):
        model = _get_embedding_model()
        if model is None: return None
        try:
            return model.encode(text, convert_to_numpy=True)
        except Exception: return None

    def get_cached_response(self, prompt: str, api_key: str = "") -> Optional[dict]:
        normalized = self._normalize_prompt(prompt)
        tenant_salt = hashlib.sha256(api_key.encode()).hexdigest()[:16] if api_key else "global"
        prompt_hash = hashlib.sha256(f"{tenant_salt}:{normalized}".encode()).hexdigest()

        if self.redis:
            try:
                cached_data = self.redis.get(f"cache:{prompt_hash}")
                if cached_data:
                    return json.loads(cached_data)
            except Exception: pass
            # Try in-memory fallback (thread-safe)
        with self._mem_lock:
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
                
                with self._mem_lock:
                    if best_hash in self._memory_cache:
                        return self._memory_cache[best_hash]

        return None

    def set_cached_response(self, prompt: str, response: dict, ttl: int = 3600, api_key: str = ""):
        """
        Store response in cache with both exact hash and FAISS embedding vector.
        Thread-safe locks ensure no corruption during concurrent writes.
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
                with self._mem_lock:
                    self._memory_cache[prompt_hash] = response
        else:
            # 2. Fallback to bounded LRU memory cache (thread-safe)
            with self._mem_lock:
                self._memory_cache[prompt_hash] = response

        embedding = self._get_embedding(normalized)
        if embedding is not None:
            self._vector_index.add(prompt_hash, embedding)


semantic_cache = SemanticCache()
