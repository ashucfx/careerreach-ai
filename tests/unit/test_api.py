from careerreach.config import get_settings
from careerreach.main import app
from fastapi.testclient import TestClient


def test_health_and_agent_catalog_do_not_require_model_credentials(monkeypatch) -> None:
    monkeypatch.delenv("CAREERREACH_MODEL_API_KEY", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        agents = client.get("/api/v1/agents").json()
        assert len(agents) == 12
        response = client.post(
            "/api/v1/workflows/plan",
            json={"goal": "Research suitable backend engineering roles"},
        )
        assert response.status_code == 503
        assert "CAREERREACH_MODEL_API_KEY" in response.json()["detail"]
    get_settings.cache_clear()
