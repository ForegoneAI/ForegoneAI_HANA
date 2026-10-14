"""Milestone 2.1: the web app can call the API from an allowed origin only."""

from fastapi.testclient import TestClient

from backend.app import main


def _preflight(origin: str):
    return TestClient(main.app).options(
        "/api/h9n/repe/extract",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_the_web_app_origin_may_call_the_api_with_a_token():
    response = _preflight("http://localhost:3000")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_other_origins_are_not_allowed():
    response = _preflight("https://evil.example")

    assert "access-control-allow-origin" not in response.headers


def test_every_method_the_api_uses_is_allowed():
    # PUT is how a mandate is edited (M3.1); a missing method fails only in the browser.
    for method in ("GET", "POST", "PUT", "PATCH"):
        response = TestClient(main.app).options(
            "/api/h9n/mandates",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method},
        )
        assert response.status_code == 200, method
