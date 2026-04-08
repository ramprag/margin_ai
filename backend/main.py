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
    """
    Pre-warm heavy NLP models during container boot (not on first request).
    This eliminates the 120-second cold-start penalty that kills the first user's experience.
    """
    logger.info("Margin AI Gateway starting up — pre-warming NLP engines...")

    # 1. Warm up Presidio (PII detection) — run in threadpool since it's CPU-heavy
    try:
        from backend.core.security import SecurityService
        await run_in_threadpool(SecurityService.redact_pii, "warmup test with email test@test.com")
        logger.info("✅ Presidio PII engine warmed up.")
    except Exception as e:
        logger.warning(f"⚠️ Presidio warmup failed: {e}")

    # 2. Warm up Sentence Transformers (Semantic Cache + Routing)
    try:
        from backend.core.cache import semantic_cache
        await run_in_threadpool(semantic_cache._get_embedding, "warmup query")
        logger.info("✅ Sentence-transformer embedding model warmed up.")
    except Exception as e:
        logger.warning(f"⚠️ Embedding model warmup failed: {e}")

    # 3. Warm up Routing exemplar embeddings
    try:
        from backend.core.router import routing_engine
        await run_in_threadpool(routing_engine._ensure_exemplar_embeddings)
        logger.info("✅ Routing classifier exemplars warmed up.")
    except Exception as e:
        logger.warning(f"⚠️ Routing warmup failed: {e}")

    logger.info("🚀 Margin AI Gateway is READY — all engines loaded.")


@app.get("/")
async def root():
    return FileResponse("backend/static/index.html")

@app.get("/api/stats")
async def get_stats():
    """
    Live Analytics API for the CFO Dashboard.
    """
    return stats_service.get_stats()


def _sanitize_all_messages(messages, security_svc):
    """
    Run PII redaction on ALL messages in the conversation history,
    not just the last one. This prevents data leaks from system prompts
    and prior turns that contain sensitive info like SSNs or API keys.

    Uses the Vision-safe get_text_content()/set_text_content() helpers
    so it never crashes on multimodal payloads.
    """
    for msg in messages:
        text = msg.get_text_content()
        if text and text.strip():
            sanitized = security_svc.redact_pii(text)
            msg.set_text_content(sanitized)


def _log_stream_completion(
    target_model: str,
    strategy: str,
    full_text: str,
    start_time: float,
    tenant_key: str,
    sanitized_prompt: str,
):
    """
    Background task that runs AFTER a streaming response is fully sent.
    This solves the 'Ghost Traffic' problem: streaming requests are now
    logged to the database and cached for future use.
    """
    try:
        latency_ms = int((time.time() - start_time) * 1000)

        # Estimate tokens from the captured text
        try:
            from backend.core.analytics import analytics_service
            input_tokens = analytics_service.count_tokens(sanitized_prompt)
            output_tokens = analytics_service.count_tokens(full_text)
        except Exception:
            # Rough fallback: ~4 chars per token
            input_tokens = max(1, len(sanitized_prompt) // 4)
            output_tokens = max(1, len(full_text) // 4)

        total_tokens = input_tokens + output_tokens
        actual_cost = analytics_service.calculate_cost(target_model, input_tokens, output_tokens)

        # Build a completion-like record for the database
        stream_record = {
            "id": f"stream-{uuid.uuid4()}",
            "model": target_model,
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
            "margin_ai_optimized": True,
            "strategy": strategy,
            "latency_ms": latency_ms,
            "estimated_cost": actual_cost,
            "cached": False,
            "choices": [{"message": {"role": "assistant", "content": full_text[:500]}}],
        }

        # Log to database for the CFO Dashboard
        db_manager.log_request(stream_record)

        # Update Semantic Cache so future identical prompts are instant
        semantic_cache.set_cached_response(sanitized_prompt, stream_record, api_key=tenant_key)

        logger.info(
            f"[STREAM LOG] model={target_model} tokens={total_tokens} "
            f"cost=${actual_cost:.6f} latency={latency_ms}ms"
        )
    except Exception as e:
        logger.error(f"Failed to log streaming request: {e}")


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    """
    Production-grade AI Gateway with Governance and ROI tracking.
    Supports both blocking and SSE streaming modes.
    All CPU-heavy ML calls are offloaded to the threadpool.
    """
    start_time = time.time()
    
    try:
        raw_body = await request.json()
        req_data = ChatCompletionRequest(**raw_body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request format: {str(e)}")
    
    if not req_data.messages:
        raise HTTPException(status_code=400, detail="Messages list is empty")
    
    # Extract the last user message safely (Vision-safe)
    last_msg = req_data.messages[-1]
    last_user_text = last_msg.get_text_content()
    
    # 1. Security Firewall — Injection Detection (on plaintext only)
    #    check_prompt_injection is fast (regex), no threadpool needed
    if last_user_text:
        is_injection, matched_pattern = security_service.check_prompt_injection(last_user_text)
        if is_injection:
            logger.warning(f"Blocked injection attempt: {last_user_text[:50]}...")
            db_manager.log_security_event(
                event_type="injection_blocked",
                pattern_matched=matched_pattern,
                prompt_preview=last_user_text,
                source_ip=request.client.host if request.client else None
            )
            raise HTTPException(status_code=400, detail="Security Block: Potential injection detected.")
    
    # 2. PII Redaction — Full conversation history, Vision-safe
    #    Presidio is CPU-heavy, offload to threadpool to avoid blocking the event loop
    await run_in_threadpool(_sanitize_all_messages, req_data.messages, security_service)
    
    # Re-extract sanitized text for cache key
    sanitized_prompt = last_msg.get_text_content()
    
    # Extract tenant key for cache isolation
    tenant_key = api_key or ""
    
    # 3. Semantic Cache Bypass (tenant-isolated)
    #    Embedding generation is CPU-heavy, offload to threadpool
    if not req_data.stream:
        cached = await run_in_threadpool(
            semantic_cache.get_cached_response, sanitized_prompt, tenant_key
        )
        if cached:
            logger.info("Semantic Cache Hit")
            cache_hit_id = f"cache-{uuid.uuid4()}"
            response_data = {**cached, "id": cache_hit_id, "margin_ai_optimized": True, "cached": True}
            response_data["strategy"] = "cache"
            response_data["latency_ms"] = int((time.time() - start_time) * 1000)
            response_data["estimated_cost"] = 0.0
            db_manager.log_request(response_data)
            return response_data
    
    # 4. Intelligent Model Routing
    #    Embedding classification is CPU-heavy for ambiguous prompts, offload to threadpool
    target_model, strategy = await run_in_threadpool(
        routing_engine.determine_model, sanitized_prompt
    )
    req_data.model = target_model
    
    # 5. Shadow Testing (Optional background fork, blocking mode only)
    if not req_data.stream:
        from backend.config import is_valid_key
        if is_valid_key(settings.OPENAI_API_KEY):
            await shadow_engine.fork_shadow_request(req_data.model_dump(exclude_none=True))
    
    # ── STREAMING PATH ──────────────────────────────────────────────
    if req_data.stream:
        body = req_data.model_dump(exclude_none=True)
        captured_text_parts = []  # Mutable list to capture streamed content

        async def stream_generator():
            """
            Stream interceptor: yields SSE chunks to the client AND
            captures the full response text for post-stream analytics.
            """
            async for chunk in cascade_manager.stream_with_cascade(body):
                # Try to extract the text delta from the chunk for analytics
                try:
                    if chunk.startswith("data: ") and chunk != "data: [DONE]":
                        data = json.loads(chunk[6:])
                        delta_content = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta_content:
                            captured_text_parts.append(delta_content)
                except (json.JSONDecodeError, IndexError, KeyError):
                    pass
                yield chunk + "\n\n"

        # Register the background task to log analytics AFTER the stream finishes
        background_tasks.add_task(
            _log_stream_completion,
            target_model=target_model,
            strategy=strategy,
            full_text="".join(captured_text_parts),
            start_time=start_time,
            tenant_key=tenant_key,
            sanitized_prompt=sanitized_prompt,
        )

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
            background=background_tasks,
        )

    # ── BLOCKING PATH ───────────────────────────────────────────────
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
    
    # Update Semantic Cache (tenant-isolated) — offload embedding to threadpool
    await run_in_threadpool(
        semantic_cache.set_cached_response, sanitized_prompt, completion_data, 3600, tenant_key
    )
    
    return completion_data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
