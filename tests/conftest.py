import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture(scope="module")
def client():
    """
    Standard fixture for integration testing of the FastAPI app.
    Usage: def test_something(client): ...
    """
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope="module")
def auth_headers():
    """Returns headers with a valid internal test key."""
    return {"Authorization": "Bearer margin-demo-key"}
