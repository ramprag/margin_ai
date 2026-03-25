from fastapi import Request, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from backend.config import settings

API_KEY_NAME = "Authorization"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    """
    Simple API Key validation. 
    In production, this would check against the database of clients.
    """
    if not api_key:
        raise HTTPException(status_code=403, detail="Could not validate credentials")
        
    expected_key = f"Bearer {settings.OPENAI_API_KEY}" # Simple override for demo
    if api_key != expected_key and not api_key.startswith("Bearer margin-"):
         raise HTTPException(status_code=403, detail="Invalid API Key")
         
    return api_key
