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
        assert client.get("/api/v1/profile").status_code == 401
        assert client.get("/api/v1/resumes").status_code == 401
        too_large = client.post(
            "/api/v1/resumes",
            files={"file": ("large.pdf", b"x" * (6 * 1024 * 1024), "application/pdf")},
        )
        assert too_large.status_code == 413
        response = client.post(
            "/api/v1/workflows/plan",
            json={"goal": "Research suitable backend engineering roles"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication is required."
    get_settings.cache_clear()
