import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # API Configurations
    API_V1_STR: str = "/v1"
    PROJECT_NAME: str = "Margin AI Gateway"
    
    # Provider Keys
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "your-key-here")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "your-key-here")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "your-key-here")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "your-key-here")
    
    # Model Thresholds (For Routing)
    COST_THRESHOLD: float = 0.5  # Max $ per 1M tokens for "cheap" queries
    SIMILARITY_THRESHOLD: float = 0.95 # For semantic caching
    
    # Infrastructure
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/marginai")
    
    # Security
    PII_REDACTION_ENABLED: bool = True
    PROMPT_INJECTION_CHECK_ENABLED: bool = True
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

settings = Settings()

def is_valid_key(key: str) -> bool:
    if not key:
        return False
    placeholders = ["your-key-here", "your_openai", "your_anthropic", "your_gemini", "your_groq"]
    for p in placeholders:
        if p in key:
            return False
    return True
