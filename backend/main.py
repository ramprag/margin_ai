from fastapi import FastAPI, Request, HTTPException, Response, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
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
import uuid
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


@app.on_event("startup")
async def warmup_models():
    """Pre-warm heavy NLP models during container boot."""
    logger.info("Margin AI Gateway starting up...")
    try:
        from backend.core.security import SecurityService
        await run_in_threadpool(SecurityService.redact_pii, "warmup test")
    except Exception: pass
    try:
        await run_in_threadpool(semantic_cache._get_embedding, "warmup")
    except Exception: pass
    try:
        await run_in_threadpool(routing_engine._ensure_exemplar_embeddings)
    except Exception: pass
    logger.info("🚀 Margin AI Gateway is READY.")


@app.get("/")
async def root():
    return FileResponse("backend/static/index.html")

@app.get("/api/stats")
async def get_stats():
    return stats_service.get_stats()


def _sanitize_all_messages(messages, security_svc):
    """Scan full conversation history for PII."""
    for msg in messages:
        text = msg.get_text_content()
        if text and text.strip():
            sanitized = security_svc.redact_pii(text)
            msg.set_text_content(sanitized)


def _log_stream_completion(
    target_model: str,
    strategy: str,
    captured_text_parts: list,  # RECEIVED AS LIST REFERENCE
    start_time: float,
    tenant_key: str,
    sanitized_prompt: str,
):
    """
    Background Task: Processes streaming analytics AFTER the stream ends.
    Deferred evaluation (joining the list here) ensures accurate token counts.
    """
    try:
        full_text = "".join(captured_text_parts)  # JOIN HERE, NOT IN add_task
        if not full_text:
            return

        latency_ms = int((time.time() - start_time) * 1000)
        
        from backend.core.analytics import analytics_service
        input_tokens = analytics_service.count_tokens(sanitized_prompt)
        output_tokens = analytics_service.count_tokens(full_text)
        actual_cost = analytics_service.calculate_cost(target_model, input_tokens, output_tokens)

        stream_record = {
            "id": f"stream-{uuid.uuid4()}",
            "model": target_model,
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            "margin_ai_optimized": True,
            "strategy": strategy,
            "latency_ms": latency_ms,
            "estimated_cost": actual_cost,
            "cached": False,
            "choices": [{"message": {"role": "assistant", "content": full_text[:200] + "..."}}],
        }

        db_manager.log_request(stream_record)
        semantic_cache.set_cached_response(sanitized_prompt, stream_record, api_key=tenant_key)
        logger.info(f"[STREAM LOG] cost=${actual_cost:.6f} latency={latency_ms}ms")
    except Exception as e:
        logger.error(f"Stream logging failed: {e}")


async def cached_stream_generator(cached_response: dict):
    """Simulate a stream from cached data."""
    id_str = f"chatcmpl-{uuid.uuid4()}"
    created = int(time.time())
    model = cached_response.get("model", "cached-model")
    
    # Extract text from the cached message
    choices = cached_response.get("choices", [{}])
    full_text = choices[0].get("message", {}).get("content", "")
    
    # Yield in rough "chunks" for SSE effect
    words = full_text.split(" ")
    for i in range(0, len(words), 5):
        chunk_text = " ".join(words[i:i+5]) + (" " if i+5 < len(words) else "")
        chunk = {
            "id": id_str,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": chunk_text}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        # Immediate yield, no real delay needed but simulates protocol
    
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    start_time = time.time()
    
    try:
        raw_body = await request.json()
        req_data = ChatCompletionRequest(**raw_body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")
    
    # 1. Security & Pre-processing
    last_msg = req_data.messages[-1]
    input_text = last_msg.get_text_content()
    
    if input_text:
        is_inj, pat = security_service.check_prompt_injection(input_text)
        if is_inj:
            db_manager.log_security_event("injection_blocked", pat, input_text, request.client.host if request.client else None)
            raise HTTPException(status_code=400, detail="Security Block: Injection detected.")
    
    await run_in_threadpool(_sanitize_all_messages, req_data.messages, security_service)
    sanitized_prompt = last_msg.get_text_content()
    tenant_key = api_key or ""
    
    # 2. Semantic Cache Lookup (NOW INCLUDES STREAMING)
    cached = await run_in_threadpool(semantic_cache.get_cached_response, sanitized_prompt, tenant_key)
    if cached:
        logger.info("Cache Hit!")
        if req_data.stream:
            # ROI/Analytics tracking for cached stream
            cached["cached"] = True
            cached["latency_ms"] = int((time.time() - start_time) * 1000)
            db_manager.log_request(cached)
            return StreamingResponse(cached_stream_generator(cached), media_type="text/event-stream")
        else:
            cached["id"] = f"cache-{uuid.uuid4()}"
            cached["cached"] = True
            cached["latency_ms"] = int((time.time() - start_time) * 1000)
            db_manager.log_request(cached)
            return cached
    
    # 3. Routing
    target_model, strategy = await run_in_threadpool(routing_engine.determine_model, sanitized_prompt)
    req_data.model = target_model
    
    # ── STREAMING PATH ──────────────────────────────────────────────
    if req_data.stream:
        body = req_data.model_dump(exclude_none=True)
        captured_text_parts = []  # Pass this reference into the task

        async def stream_generator():
            async for chunk in cascade_manager.stream_with_cascade(body):
                try:
                    if chunk.startswith("data: ") and chunk != "data: [DONE]":
                        data = json.loads(chunk[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta: captured_text_parts.append(delta)
                except Exception: pass
                yield chunk + "\n\n"

        background_tasks.add_task(
            _log_stream_completion,
            target_model=target_model,
            strategy=strategy,
            captured_text_parts=captured_text_parts,  # PASSING LIST REFERENCE
            start_time=start_time,
            tenant_key=tenant_key,
            sanitized_prompt=sanitized_prompt,
        )

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
            background=background_tasks,
        )

    # ── BLOCKING PATH ───────────────────────────────────────────────
    try:
        completion_data = await cascade_manager.execute_with_cascade(req_data.model_dump(exclude_none=True))
    except Exception as e:
        logger.error(f"Upstream Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Margin AI internal gateway error")
    
    latency_ms = int((time.time() - start_time) * 1000)
    input_tokens = completion_data.get("usage", {}).get("prompt_tokens", 0)
    output_tokens = completion_data.get("usage", {}).get("completion_tokens", 0)
    actual_cost = analytics_service.calculate_cost(target_model, input_tokens, output_tokens)
    
    completion_data.update({
        "margin_ai_optimized": True,
        "strategy": strategy,
        "latency_ms": latency_ms,
        "estimated_cost": actual_cost
    })
    
    db_manager.log_request(completion_data)
    await run_in_threadpool(semantic_cache.set_cached_response, sanitized_prompt, completion_data, 3600, tenant_key)
    
    return completion_data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
