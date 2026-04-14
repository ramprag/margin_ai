import pytest
from backend.core.security import SecurityService
from backend.core.cache import FAISSIndex
from backend.core.router import RoutingEngine
from backend.core.schemas import ChatMessage

# 1. Test Privacy Firewall
def test_pii_redaction():
    svc = SecurityService()
    text = "Contact me at ram.prag@fintech.com or call 4532-1234-5678-9012"
    sanitized = svc.redact_pii(text)
    
    assert "@" not in sanitized
    assert "4532" not in sanitized
    assert "[EMAIL_ADDRESS]" in sanitized or "[EMAIL]" in sanitized
    assert "[CREDIT_CARD]" in sanitized or "[CARD]" in sanitized

# 2. Test FAISS Index Synchronization (The "No Desync" Proof)
def test_faiss_sync():
    # Use max_size=2 to force eviction immediately
    index = FAISSIndex(max_size=2)
    
    # Add 3 items (forcing 1 eviction)
    index.add("hash_1", [0.1] * 384)
    index.add("hash_2", [0.2] * 384)
    index.add("hash_3", [0.3] * 384)
    
    assert index.size == 2
    # Verify hash_1 is gone and hash_2 & 3 are mapped correctly
    assert index.search([0.1] * 384, 0.9) is None
    assert index.search([0.2] * 384, 0.9) == "hash_2"
    assert index.search([0.3] * 384, 0.9) == "hash_3"

# 3. Test Routing Logic
def test_routing_intent():
    engine = RoutingEngine()
    
    # Efficiency task
    model_e, strat_e = engine.determine_model("Hi there")
    assert strat_e == "efficiency"
    
    # Reasoning task
    model_r, strat_r = engine.determine_model("Compare the architectural tradeoffs between Kafka and RabbitMQ for high-throughput streaming.")
    assert strat_r == "reasoning"
