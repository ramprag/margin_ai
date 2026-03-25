import tiktoken
from datetime import datetime
import uuid

class AnalyticsService:
    """
    Tracks token usage, costs, and calculate ROI on the fly.
    """
    def __init__(self):
        self.encoding = tiktoken.get_encoding("cl100k_base")
        # Approx cost per 1M tokens ($)
        self.pricing = {
            "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
            "gpt-4o": {"input": 5.0, "output": 15.0},
            "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08}, 
            "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
            "gemini-1.5-flash": {"input": 0.075, "output": 0.3},
            "gemini-1.5-pro": {"input": 3.5, "output": 10.5}
        }

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        prices = self.pricing.get(model, self.pricing["gpt-4o"]) # Default to gpt-4o price if unknown
        return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000

    def calculate_roi(self, actual_cost: float, strong_model_total_cost: float) -> float:
        """
        Returns the % saved vs. using the strong model for everything.
        """
        if strong_model_total_cost == 0: return 0.0
        return ((strong_model_total_cost - actual_cost) / strong_model_total_cost) * 100

analytics_service = AnalyticsService()
