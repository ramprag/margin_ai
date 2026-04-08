from fastapi import FastAPI, Request, HTTPException, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from backend.config import settings
from backend.core.security import security_service
from backend.core.router import routing_engine
from backend.core.cache import semantic_cache
from backend.core.analytics import analytics_service
from backend.core.stats import stats_service
from backend.core.providers import provider_factory
from backend.core.schemas import ChatCompletionRequest, ChatCompletionResponse
from backend.core.auth import get_api_key
from backend.core.cascade import cascade_manager
from backend.core.database import db_manager
from backend.core.shadow import shadow_engine
import httpx
import logging
import json
import time
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.PROJECT_NAME)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serving the Dashboard
os.makedirs("backend/static", exist_ok=True)
app.mount("/dashboard", StaticFiles(directory="backend/static", html=True), name="static")

@app.get("/")
async def root():
    return FileResponse("backend/static/index.html")

@app.get("/api/stats")
async def get_stats():
    """
    Live Analytics API for the CFO Dashboard.
    """
    return stats_service.get_stats()

@app.post("/v1/chat/completions")
async def chat_completions(request: Request, api_key: str = Depends(get_api_key)):
    """
    Production-grade AI Gateway with Governance and ROI tracking.
    """
    start_time = time.time()
    
    try:
        raw_body = await request.json()
        req_data = ChatCompletionRequest(**raw_body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request format: {str(e)}")
    
    if not req_data.messages:
        raise HTTPException(status_code=400, detail="Messages list is empty")
        
    last_user_message_obj = req_data.messages[-1]
    last_user_message = last_user_message_obj.content
    
    # 1. Security Firewall (PII & Injection)
    is_injection, matched_pattern = security_service.check_prompt_injection(last_user_message)
    if is_injection:
        logger.warning(f"Blocked injection attempt: {last_user_message[:50]}...")
        # Log the real security event to the database for the CFO Dashboard
        db_manager.log_security_event(
            event_type="injection_blocked",
            pattern_matched=matched_pattern,
            prompt_preview=last_user_message,
            source_ip=request.client.host if request.client else None
        )
        raise HTTPException(status_code=400, detail="Security Block: Potential injection detected.")
    
    sanitized_prompt = security_service.redact_pii(last_user_message)
    last_user_message_obj.content = sanitized_prompt
    
    # 2. Semantic Cache Bypass
    cached = semantic_cache.get_cached_response(sanitized_prompt)
    if cached:
        import uuid
        logger.info("Semantic Cache Hit")
        # Ensure cache hit has a unique ID for the logging table to avoid primary key conflicts
        cache_hit_id = f"cache-{uuid.uuid4()}"
        response_data = {**cached, "id": cache_hit_id, "margin_ai_optimized": True, "cached": True}
        response_data["strategy"] = "cache"
        response_data["latency_ms"] = int((time.time() - start_time) * 1000)
        response_data["estimated_cost"] = 0.0
        db_manager.log_request(response_data)
        return response_data
        
    # 3. Intelligent Model Routing
    target_model, strategy = routing_engine.determine_model(sanitized_prompt)
    req_data.model = target_model
    
    # 4. Shadow Testing (Optional background fork)
    from backend.config import is_valid_key
    if is_valid_key(settings.OPENAI_API_KEY):
        await shadow_engine.fork_shadow_request(req_data.model_dump(exclude_none=True))
    
    # 5. Cascading Provider Gateway
    try:
        completion_data = await cascade_manager.execute_with_cascade(req_data.model_dump(exclude_none=True))
    except httpx.HTTPStatusError as e:
        logger.error(f"Upstream Error: {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail="AI Provider unavailable")
    except Exception as e:
        logger.error(f"Gateway Infrastructure Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Margin AI internal gateway error")
    
    # 6. Post-Processing, Analytics & Persistence
    latency_ms = int((time.time() - start_time) * 1000)
    
    input_tokens = completion_data.get("usage", {}).get("prompt_tokens", 0)
    output_tokens = completion_data.get("usage", {}).get("completion_tokens", 0)
    actual_cost = analytics_service.calculate_cost(target_model, input_tokens, output_tokens)
    
    # Inject Margin AI Governance Metadata
    completion_data["margin_ai_optimized"] = True
    completion_data["strategy"] = strategy
    completion_data["latency_ms"] = latency_ms
    completion_data["estimated_cost"] = actual_cost
    
    # Persist to local analytics for Dashboard
    db_manager.log_request(completion_data)
    
    # Update Semantic Cache
    semantic_cache.set_cached_response(sanitized_prompt, completion_data)
    
    return completion_data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
