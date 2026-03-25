import asyncio
import logging
from typing import Dict, Any
from backend.core.providers import provider_factory

logger = logging.getLogger(__name__)

class ShadowTestingEngine:
    """
    Handles A/B shadow testing by forking traffic to a test model asynchronously.
    """
    async def fork_shadow_request(self, body: Dict[str, Any], shadow_model: str = None):
        """
        Runs a secondary request in the background for comparison.
        """
        from backend.core.router import routing_engine
        
        target_shadow = shadow_model or routing_engine.strong_model
        
        shadow_body = body.copy()
        shadow_body["model"] = target_shadow
        shadow_body["stream"] = False # Shadow requests should not stream
        
        try:
            provider = provider_factory.get_provider(shadow_model)
            # Run in background
            asyncio.create_task(self._execute_and_log(provider, shadow_body))
        except Exception as e:
            logger.error(f"Shadow test fork failed: {e}")

    async def _execute_and_log(self, provider, body):
        try:
            response = await provider.complete(body)
            # In Phase 5, we would log this to a 'comparisons' table in DB
            logger.info(f"Shadow test completed for model {body['model']}")
        except Exception as e:
            logger.error(f"Shadow execution failed: {e}")

shadow_engine = ShadowTestingEngine()
