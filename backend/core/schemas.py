from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union


class ChatMessage(BaseModel):
    """
    OpenAI-compatible message schema.
    `content` can be:
      - A plain string (standard text chat)
      - A list of dicts (Vision/multimodal: [{"type": "text", "text": "..."}, {"type": "image_url", ...}])
      - None (for function call responses where content is empty)
    """
    role: str
    content: Union[str, List[Dict[str, Any]], None] = None
    name: Optional[str] = None

    def get_text_content(self) -> str:
        """
        Safely extract text content regardless of format.
        - If content is a string, return it directly.
        - If content is a list (Vision format), extract and join all text blocks.
        - If content is None, return empty string.
        """
        if self.content is None:
            return ""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            text_parts = []
            for block in self.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            return " ".join(text_parts)
        return str(self.content)

    def set_text_content(self, new_text: str):
        """
        Safely update text content regardless of format.
        - If content is a string, replace it.
        - If content is a list (Vision format), update only the text blocks.
        - If content is None, set it to the new text.
        """
        if self.content is None or isinstance(self.content, str):
            self.content = new_text
        elif isinstance(self.content, list):
            for block in self.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    block["text"] = new_text
                    return  # Only update the first text block
            # No text block found, append one
            self.content.append({"type": "text", "text": new_text})


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = "auto"
    messages: List[ChatMessage]
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    user: Optional[str] = None


class Choice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Optional[Usage] = None
    margin_ai_optimized: bool = True
    strategy: Optional[str] = None
    latency_ms: Optional[int] = None
