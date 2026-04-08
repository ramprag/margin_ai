import logging
import json
from typing import Dict, Any, AsyncGenerator
from backend.core.providers import provider_factory

logger = logging.getLogger(__name__)

class CascadeManager:
    """
    Manages model failovers and performance-based escalations.
    Supports both blocking (complete) and streaming (stream_complete) modes.
    """
    async def execute_with_cascade(
        self, 
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Blocking mode: Attempts execution on the primary model.
        If it fails, escalates to a stronger model.
        """
        from backend.core.router import routing_engine
        
        primary_model = body.get("model")
        strong_model = routing_engine.strong_model
        
        try:
            provider = provider_factory.get_provider(primary_model)
            response = await provider.complete(body)
            return response
            
        except Exception as e:
            if primary_model == strong_model:
                raise e
                
            logger.warning(f"Primary model {primary_model} failed. Escalating to {strong_model}. Error: {str(e)}")
            body["model"] = strong_model
            provider = provider_factory.get_provider(strong_model)
            return await provider.complete(body)

    async def stream_with_cascade(
        self,
        body: Dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        """
        Streaming mode: Attempts streaming execution on the primary model.
        If it fails before yielding any data, escalates to a stronger model.
        """
        from backend.core.router import routing_engine

        primary_model = body.get("model")
        strong_model = routing_engine.strong_model

        try:
            provider = provider_factory.get_provider(primary_model)
            yielded = False
            async for chunk in provider.stream_complete(body):
                yielded = True
                yield chunk
            # If we yielded at least one chunk, we're done successfully
            if yielded:
                return
        except Exception as e:
            if primary_model == strong_model:
                # Already on the strongest model, yield error and stop
                error_chunk = json.dumps({
                    "choices": [{"index": 0, "delta": {"content": f"[Gateway Error: {str(e)}]"}}]
                })
                yield f"data: {error_chunk}\n\n"
                yield "data: [DONE]\n\n"
                return

            logger.warning(f"Primary stream {primary_model} failed. Escalating to {strong_model}. Error: {str(e)}")

        # Escalate to strong model
        body["model"] = strong_model
        provider = provider_factory.get_provider(strong_model)
        async for chunk in provider.stream_complete(body):
            yield chunk


cascade_manager = CascadeManager()
