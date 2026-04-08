from typing import Dict, Any, Tuple, List
import logging

logger = logging.getLogger(__name__)

# Lazy-loaded embedding model (shared with cache.py via the same singleton pattern)
_routing_model = None


def _get_routing_model():
    """Lazy-load the sentence-transformers model for semantic routing classification."""
    global _routing_model
    if _routing_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _routing_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("Routing classifier model loaded.")
        except ImportError:
            logger.warning("sentence-transformers not installed. Using heuristic-only routing.")
        except Exception as e:
            logger.warning(f"Failed to load routing model: {e}. Heuristic-only mode.")
    return _routing_model


def _cosine_similarity(vec_a, vec_b) -> float:
    """Compute cosine similarity between two vectors."""
    import numpy as np
    dot = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class RoutingEngine:
    """
    Hybrid Routing Engine for Margin AI Gateway.

    Layer 1 (Fast Path): Heuristic scoring based on keywords, length, and structure.
               If heuristic confidence is HIGH (score >= 6 or score <= -1),
               route immediately without ML overhead.

    Layer 2 (Smart Path): For ambiguous prompts (score 0-5), use sentence-transformer
               embeddings to classify the prompt against reference exemplar sets
               for 'complex' vs 'trivial' tasks.

    This design ensures:
    - Obvious cases ("Hi" or "Write a distributed system") are resolved in <1ms.
    - Edge cases ("Solve P=NP. Provide proof.") are correctly classified by ML.
    """
    def __init__(self):
        from backend.config import settings, is_valid_key

        # Dynamic Model Selection based on available keys
        if is_valid_key(settings.OPENAI_API_KEY):
            self.lean_model = "gpt-3.5-turbo"
            self.strong_model = "gpt-4o"
        elif is_valid_key(settings.GROQ_API_KEY):
            self.lean_model = "llama-3.1-8b-instant"
            self.strong_model = "llama-3.3-70b-versatile"
        elif is_valid_key(settings.GEMINI_API_KEY):
            self.lean_model = "gemini-1.5-flash"
            self.strong_model = "gemini-1.5-pro"
        else:
            self.lean_model = "none"
            self.strong_model = "none"

        # Heuristic keywords
        self.complexity_keywords = {
            "high": [
                "analyze", "summarize the entire", "write a professional",
                "code", "architecture", "solve", "prove", "design",
                "audit", "compare and contrast", "evaluate", "debug",
                "refactor", "optimize", "implement", "explain why",
                "mathematical", "algorithm", "theorem",
            ],
            "low": [
                "hello", "hi", "how are you", "what time is it",
                "who won", "simple question", "format this",
                "extract the", "list the", "convert to",
                "translate this", "what is the date",
            ]
        }

        # Exemplar sets for the embedding classifier (Layer 2)
        # These are reference prompts that define what "complex" and "trivial" look like
        self.complex_exemplars: List[str] = [
            "Design a distributed system for processing real-time financial transactions",
            "Analyze the legal implications of this contract clause for GDPR compliance",
            "Write a production-grade authentication system with OAuth2 and PKCE",
            "Solve this differential equation and explain each step of the proof",
            "Audit this smart contract for reentrancy vulnerabilities",
            "Compare the architectural tradeoffs between microservices and monolith",
            "Debug this race condition in our concurrent task queue implementation",
            "Evaluate the financial risk model using Monte Carlo simulation",
            "Prove that this algorithm runs in O(n log n) time complexity",
            "Refactor this legacy codebase to use dependency injection patterns",
        ]

        self.trivial_exemplars: List[str] = [
            "Hi there, how are you doing today?",
            "What time is it?",
            "Format this JSON array for me",
            "Extract the email address from this text",
            "Convert 100 dollars to euros",
            "Translate hello to Spanish",
            "What is the capital of France?",
            "List the days of the week",
            "Summarize this in one sentence: The cat sat on the mat",
            "What is 2 + 2?",
        ]

        # Pre-computed embeddings for exemplars (lazy-loaded)
        self._complex_embeddings = None
        self._trivial_embeddings = None

    def _ensure_exemplar_embeddings(self):
        """Pre-compute embeddings for exemplar sets (only once)."""
        if self._complex_embeddings is not None:
            return True

        model = _get_routing_model()
        if model is None:
            return False

        try:
            self._complex_embeddings = model.encode(self.complex_exemplars, convert_to_numpy=True)
            self._trivial_embeddings = model.encode(self.trivial_exemplars, convert_to_numpy=True)
            logger.info("Exemplar embeddings pre-computed for hybrid routing.")
            return True
        except Exception as e:
            logger.error(f"Failed to compute exemplar embeddings: {e}")
            return False

    def _heuristic_score(self, prompt: str) -> int:
        """
        Layer 1: Fast heuristic scoring based on keywords, length, and structure.
        Returns an integer score where:
        - Higher score = more complex
        - Lower/negative score = more trivial
        """
        score = 0
        prompt_low = prompt.lower()
        word_count = len(prompt.split())

        # Signal 1: High-complexity keyword matches
        for kw in self.complexity_keywords["high"]:
            if kw in prompt_low:
                score += 3

        # Signal 2: Low-complexity keyword matches
        for kw in self.complexity_keywords["low"]:
            if kw in prompt_low:
                score -= 2

        # Signal 3: Length as a weak signal (not dominant)
        if word_count > 150:
            score += 1
        elif word_count < 8:
            score -= 1

        # Signal 4: Structural cues
        if "{" in prompt and "}" in prompt:  # Likely JSON/Code
            score += 2
        if "```" in prompt:  # Code block
            score += 2
        if "?" in prompt and word_count < 15:  # Short question
            score -= 1

        return score

    def _classify_with_embeddings(self, prompt: str) -> Tuple[str, float, float]:
        """
        Layer 2: Embedding-based classification for ambiguous prompts.
        Computes average cosine similarity against complex and trivial exemplar sets.

        Returns:
            (classification: str, avg_complex_sim: float, avg_trivial_sim: float)
        """
        if not self._ensure_exemplar_embeddings():
            return "unknown", 0.0, 0.0

        model = _get_routing_model()
        if model is None:
            return "unknown", 0.0, 0.0

        try:
            prompt_embedding = model.encode(prompt, convert_to_numpy=True)

            # Average similarity against complex exemplars
            complex_sims = [
                _cosine_similarity(prompt_embedding, ce)
                for ce in self._complex_embeddings
            ]
            avg_complex = sum(complex_sims) / len(complex_sims) if complex_sims else 0.0

            # Average similarity against trivial exemplars
            trivial_sims = [
                _cosine_similarity(prompt_embedding, te)
                for te in self._trivial_embeddings
            ]
            avg_trivial = sum(trivial_sims) / len(trivial_sims) if trivial_sims else 0.0

            if avg_complex > avg_trivial:
                return "complex", avg_complex, avg_trivial
            else:
                return "trivial", avg_complex, avg_trivial

        except Exception as e:
            logger.error(f"Embedding classification failed: {e}")
            return "unknown", 0.0, 0.0

    def determine_model(self, prompt: str) -> Tuple[str, str]:
        """
        Hybrid routing decision engine.

        Returns:
            Tuple of (model_name: str, strategy: str)
        """
        score = self._heuristic_score(prompt)

        # Layer 1: High-confidence heuristic decisions (skip ML)
        if score >= 6:
            logger.info(f"[ROUTER] Heuristic STRONG | score={score}")
            return (self.strong_model, "intensive_reasoning")

        if score <= -1:
            logger.info(f"[ROUTER] Heuristic LEAN | score={score}")
            return (self.lean_model, "efficiency_optimized")

        # Layer 2: Ambiguous zone (score 0-5) — invoke embedding classifier
        classification, avg_complex, avg_trivial = self._classify_with_embeddings(prompt)

        if classification == "complex":
            logger.info(
                f"[ROUTER] Classifier STRONG | heuristic_score={score} | "
                f"sim_complex={avg_complex:.3f} sim_trivial={avg_trivial:.3f}"
            )
            return (self.strong_model, "intensive_reasoning")
        elif classification == "trivial":
            logger.info(
                f"[ROUTER] Classifier LEAN | heuristic_score={score} | "
                f"sim_complex={avg_complex:.3f} sim_trivial={avg_trivial:.3f}"
            )
            return (self.lean_model, "efficiency_optimized")
        else:
            # Classifier unavailable or inconclusive — fall back to heuristic
            if score >= 3:
                logger.info(f"[ROUTER] Fallback STRONG | score={score} (classifier unavailable)")
                return (self.strong_model, "balanced_performance")
            else:
                logger.info(f"[ROUTER] Fallback LEAN | score={score} (classifier unavailable)")
                return (self.lean_model, "balanced_performance")


routing_engine = RoutingEngine()
