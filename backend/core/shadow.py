import asyncio
import time
import logging
from typing import Dict, Any
from backend.core.providers import provider_factory

logger = logging.getLogger(__name__)

class ShadowTestingEngine:
    """
    Handles A/B shadow testing by forking traffic to a test model asynchronously.
    Compares primary model responses against a stronger model in the background
    to measure quality drift and cost arbitrage effectiveness.
    """
    async def fork_shadow_request(self, body: Dict[str, Any], shadow_model: str = None):
        """
        Runs a secondary request in the background for comparison.
        """
        from backend.core.router import routing_engine
        
        target_shadow = shadow_model or routing_engine.strong_model
        
        # Don't shadow-test against the same model we're already using
        if body.get("model") == target_shadow:
            return
        
        shadow_body = body.copy()
        shadow_body["model"] = target_shadow
        shadow_body["stream"] = False  # Shadow requests should not stream
        
        try:
            provider = provider_factory.get_provider(target_shadow)
            # Run in background — wrap in error-safe task
            task = asyncio.create_task(self._execute_and_log(provider, shadow_body))
            # Prevent unhandled task exceptions from crashing the event loop
            task.add_done_callback(self._handle_task_exception)
        except Exception as e:
            logger.error(f"Shadow test fork failed: {e}")

    def _handle_task_exception(self, task: asyncio.Task):
        """Silently catch and log any unhandled exceptions from background tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Shadow background task failed: {exc}")

    async def _execute_and_log(self, provider, body):
        start = time.time()
        try:
            response = await provider.complete(body)
            latency_ms = int((time.time() - start) * 1000)
            logger.info(
                f"Shadow test completed | model={body['model']} | "
                f"latency={latency_ms}ms | "
                f"tokens={response.get('usage', {}).get('total_tokens', 'N/A')}"
            )
        except Exception as e:
            logger.error(f"Shadow execution failed for {body.get('model')}: {e}")

shadow_engine = ShadowTestingEngine()
