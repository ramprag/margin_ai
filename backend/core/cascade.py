import logging
from typing import Dict, Any, Callable, Awaitable
from backend.core.providers import provider_factory

logger = logging.getLogger(__name__)

class CascadeManager:
    """
    Manages model failovers and performance-based escalations.
    """
    async def execute_with_cascade(
        self, 
        body: Dict[str, Any], 
        on_success: Callable[[Dict[str, Any]], Awaitable[None]] = None
    ) -> Dict[str, Any]:
        """
        Attempts execution on the primary model. If it fails or quality 
        is suspected to be low, escalates to a stronger model.
        """
        from backend.core.router import routing_engine
        
        primary_model = body.get("model")
        strong_model = routing_engine.strong_model
        
        try:
            provider = provider_factory.get_provider(primary_model)
            response = await provider.complete(body)
            
            # TODO: Add dynamic confidence scoring based on response content
            # For now, we only cascade on actual provider errors
            return response
            
        except Exception as e:
            if primary_model == strong_model:
                # We already tried the strongest model
                raise e
                
            logger.warning(f"Primary model {primary_model} failed. Escalating to {strong_model}. Error: {str(e)}")
            body["model"] = strong_model
            provider = provider_factory.get_provider(strong_model)
            return await provider.complete(body)

cascade_manager = CascadeManager()
