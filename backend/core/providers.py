import httpx
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, AsyncGenerator, Optional
from backend.config import settings

logger = logging.getLogger(__name__)

class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def stream_complete(self, body: Dict[str, Any]) -> AsyncGenerator[str, None]:
        pass

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str):
        from backend.config import is_valid_key
        if not is_valid_key(api_key):
            self.api_key = None
        else:
            self.api_key = api_key
        self.url = "https://api.openai.com/v1/chat/completions"

    async def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "error": "API Key not configured. Please set OPENAI_API_KEY in your .env file.",
                "choices": [{"message": {"content": "[ERROR: API Key Missing]"}}]
            }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()

    async def stream_complete(self, body: Dict[str, Any]) -> AsyncGenerator[str, None]:
        body["stream"] = True
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=60.0
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_lines():
                    if chunk.startswith("data: "):
                        yield chunk

class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str):
        from backend.config import is_valid_key
        if not is_valid_key(api_key):
            self.api_key = None
        else:
            self.api_key = api_key
        self.url = "https://api.anthropic.com/v1/messages"

    async def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "error": "API Key not configured",
                "choices": [{"message": {"content": "[ERROR: API Key Missing]"}}]
            }
        # Implementation for Anthropic API conversion
        # This is a simplified version
        anthropic_body = {
            "model": body.get("model", "claude-3-haiku-20240307"),
            "messages": body.get("messages", []),
            "max_tokens": body.get("max_tokens", 1024)
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=anthropic_body,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()

    async def stream_complete(self, body: Dict[str, Any]) -> AsyncGenerator[str, None]:
        # Implementation for Anthropic streaming
        yield "data: [Anthropic streaming not yet fully implemented]"

class GroqProvider(OpenAIProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.url = "https://api.groq.com/openai/v1/chat/completions"

class ProviderFactory:
    @staticmethod
    def get_provider(model_name: str) -> LLMProvider:
        if model_name == "none" or not model_name:
            raise ValueError("Margin AI Error: No valid API keys found in .env (OpenAI, Groq, or Gemini).")
            
        if "gpt" in model_name:
            return OpenAIProvider(settings.OPENAI_API_KEY)
        elif "claude" in model_name:
            return AnthropicProvider(settings.ANTHROPIC_API_KEY)
        elif "llama" in model_name or "mixtral" in model_name:
            # Groq is excellent for open-source models like Llama3/Mixtral
            return GroqProvider(settings.GROQ_API_KEY)
        elif "gemini" in model_name:
            # Ensure Gemini uses the Gemini key explicitly (stub)
            pass
            
        # Default to OpenAI or generic handler
        return OpenAIProvider(settings.OPENAI_API_KEY)

provider_factory = ProviderFactory()
