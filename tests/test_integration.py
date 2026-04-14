import pytest

def test_api_root(client):
    response = client.get("/")
    assert response.status_code == 200

def test_api_stats(client):
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_queries" in data
    assert "total_savings" in data

def test_chat_completions_no_auth(client):
    # Should fail with 401
    payload = {
        "model": "auto",
        "messages": [{"role": "user", "content": "hello"}]
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 401
