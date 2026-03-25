from typing import Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

class RoutingEngine:
    """
    Intelligently routes queries based on complexity, cost and performance requirements.
    """
    def __init__(self):
        from backend.config import settings, is_valid_key

        # Dynamic Model Selection based on available keys
        if is_valid_key(settings.OPENAI_API_KEY):
            self.lean_model = "gpt-3.5-turbo"
            self.strong_model = "gpt-4o"
        elif is_valid_key(settings.GROQ_API_KEY):
            # Fallback to Groq if OpenAI is missing
            self.lean_model = "llama-3.1-8b-instant"
            self.strong_model = "llama-3.3-70b-versatile" # Using correct Groq model IDs
        elif is_valid_key(settings.GEMINI_API_KEY):
            self.lean_model = "gemini-1.5-flash"
            self.strong_model = "gemini-1.5-pro"
        else:
            # Absolute fallback (prevents 'ghost' OpenAI 401s when no keys are found)
            self.lean_model = "none"
            self.strong_model = "none"

        self.complexity_keywords = {
            "high": ["analyze", "summarize the entire document", "write a professional", "code", "architecture", "solve"],
            "low": ["hello", "how are you", "what time is it", "who won", "simple question"]
        }

    def determine_model(self, prompt: str) -> Tuple[str, str]:
        """
        Multi-signal scoring system for optimal model selection.
        """
        score = 0
        prompt_low = prompt.lower()
        word_count = len(prompt.split())
        
        # Signal 1: Intent Complexity
        for kw in self.complexity_keywords["high"]:
            if kw in prompt_low:
                score += 3
                
        # Signal 2: Length (Token estimate)
        if word_count > 100:
            score += 2
        elif word_count < 10:
            score -= 1
            
        # Signal 3: Structural Signals
        if "{" in prompt and "}" in prompt: # Likely JSON/Code
            score += 2
        if "?" in prompt: # Simple question
            score += 1
 
        # Decision Thresholds
        if score >= 4:
            return (self.strong_model, "intensive_reasoning")
        if score <= 0:
            return (self.lean_model, "efficiency_optimized")
            
        return (self.lean_model, "balanced_performance")

routing_engine = RoutingEngine()
