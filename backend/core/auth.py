from fastapi import Request, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from backend.config import settings
import logging

logger = logging.getLogger(__name__)

API_KEY_NAME = "Authorization"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def _get_allowed_keys() -> set:
    """
    Parse the MARGIN_API_KEYS environment variable into a set of valid keys.
    If empty, the gateway runs in open mode (accepts all keys).
    """
    raw = getattr(settings, 'MARGIN_API_KEYS', '')
    if not raw or raw.strip() == '':
        return set()  # Open mode
    return {k.strip() for k in raw.split(',') if k.strip()}


async def get_api_key(request: Request, api_key: str = Security(api_key_header)):
    """
    API Key validation for the Margin AI Gateway.

    Behavior:
    - If MARGIN_API_KEYS is configured: only listed keys are accepted.
    - If MARGIN_API_KEYS is empty: all Bearer tokens are accepted (open gateway mode).
    - Logs which key made the request for per-client analytics.
    """
    if not api_key:
        raise HTTPException(
            status_code=403,
            detail="Missing API key. Pass your key via the Authorization header: 'Bearer <your-key>'"
        )

    # Extract the raw token from "Bearer <token>"
    token = api_key
    if api_key.startswith("Bearer "):
        token = api_key[7:]

    allowed_keys = _get_allowed_keys()

    if allowed_keys:
        # Strict mode: validate against the allowlist
        if token not in allowed_keys:
            logger.warning(f"Rejected unauthorized API key: {token[:8]}...")
            raise HTTPException(status_code=403, detail="Invalid API Key")
        logger.info(f"Authenticated request | key={token[:8]}...")
    else:
        # Open gateway mode (local dev / demo)
        logger.info(f"Open gateway mode | key={token[:8]}...")

    return api_key
