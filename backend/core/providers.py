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
    """
    Production-grade Anthropic Messages API provider.
    Translates between OpenAI ChatCompletion format and Anthropic Messages format
    so downstream clients using the OpenAI SDK see zero difference.
    """
    def __init__(self, api_key: str):
        from backend.config import is_valid_key
        if not is_valid_key(api_key):
            self.api_key = None
        else:
            self.api_key = api_key
        self.url = "https://api.anthropic.com/v1/messages"

    def _translate_to_anthropic(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert OpenAI-format request body to Anthropic Messages API format.
        Key differences:
        - Anthropic requires 'system' as a top-level field, not inside messages[].
        - Anthropic uses 'max_tokens' (required), OpenAI uses it optionally.
        """
        messages = body.get("messages", [])
        
        # Extract system message(s) from the messages array
        system_text = ""
        user_messages = []
        for msg in messages:
            role = msg.get("role", "user") if isinstance(msg, dict) else getattr(msg, "role", "user")
            content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            if role == "system":
                system_text += content + "\n"
            else:
                user_messages.append({"role": role, "content": content})

        anthropic_body = {
            "model": body.get("model", "claude-3-5-sonnet-20241022"),
            "messages": user_messages,
            "max_tokens": body.get("max_tokens", 4096),
        }

        if system_text.strip():
            anthropic_body["system"] = system_text.strip()

        # Pass through optional parameters
        if body.get("temperature") is not None:
            anthropic_body["temperature"] = body["temperature"]
        if body.get("top_p") is not None:
            anthropic_body["top_p"] = body["top_p"]
        if body.get("stop"):
            anthropic_body["stop_sequences"] = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]

        return anthropic_body

    def _translate_to_openai(self, anthropic_response: Dict[str, Any], model: str) -> Dict[str, Any]:
        """
        Convert Anthropic Messages API response to OpenAI ChatCompletion format.
        Anthropic returns:  {"content": [{"text": "..."}], "usage": {"input_tokens": N, "output_tokens": N}}
        OpenAI expects:     {"choices": [{"message": {"role": "assistant", "content": "..."}}], "usage": {...}}
        """
        # Extract the text content from Anthropic's content blocks
        content_blocks = anthropic_response.get("content", [])
        full_text = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                full_text += block.get("text", "")

        # Translate usage
        anthropic_usage = anthropic_response.get("usage", {})
        input_tokens = anthropic_usage.get("input_tokens", 0)
        output_tokens = anthropic_usage.get("output_tokens", 0)

        return {
            "id": anthropic_response.get("id", "msg_unknown"),
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_text
                },
                "finish_reason": anthropic_response.get("stop_reason", "stop")
            }],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            }
        }

    async def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "error": "API Key not configured. Please set ANTHROPIC_API_KEY in your .env file.",
                "choices": [{"message": {"content": "[ERROR: API Key Missing]"}}]
            }

        requested_model = body.get("model", "claude-3-5-sonnet-20241022")
        anthropic_body = self._translate_to_anthropic(body)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=anthropic_body,
                timeout=120.0
            )
            response.raise_for_status()
            anthropic_data = response.json()

        return self._translate_to_openai(anthropic_data, requested_model)

    async def stream_complete(self, body: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """
        Real SSE streaming for Anthropic.
        Reads Anthropic's event stream (content_block_delta) and re-emits
        each chunk as OpenAI-compatible SSE format.
        """
        if not self.api_key:
            yield 'data: {"choices": [{"delta": {"content": "[ERROR: API Key Missing]"}}]}\n\n'
            yield "data: [DONE]\n\n"
            return

        anthropic_body = self._translate_to_anthropic(body)
        anthropic_body["stream"] = True

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self.url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=anthropic_body,
                timeout=120.0
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    # Anthropic sends "event: content_block_delta" then "data: {...}"
                    if line.startswith("data: "):
                        raw = line[6:]
                        try:
                            chunk = json.loads(raw)
                            # Extract delta text from content_block_delta events
                            if chunk.get("type") == "content_block_delta":
                                delta_text = chunk.get("delta", {}).get("text", "")
                                if delta_text:
                                    openai_chunk = json.dumps({
                                        "choices": [{"index": 0, "delta": {"content": delta_text}}]
                                    })
                                    yield f"data: {openai_chunk}"
                            elif chunk.get("type") == "message_stop":
                                yield "data: [DONE]"
                        except json.JSONDecodeError:
                            continue

class GroqProvider(OpenAIProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.url = "https://api.groq.com/openai/v1/chat/completions"

class GeminiProvider(OpenAIProvider):
    def __init__(self, api_key: str):
        super().__init__(api_key)
        # Google's native OpenAI-compatible wrapper endpoint
        self.url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    
    async def complete(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Gemini requires slightly different error handling for its OpenAI endpoint."""
        try:
            return await super().complete(body)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Map Gemini model names automatically if missing
                logger.warning(f"Gemini 404 for model {body.get('model')}. Falling back to gemini-pro.")
                body["model"] = "gemini-pro"
                return await super().complete(body)
            raise e


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
            return GeminiProvider(settings.GEMINI_API_KEY)
            
        # Default to OpenAI or generic handler
        return OpenAIProvider(settings.OPENAI_API_KEY)


provider_factory = ProviderFactory()
