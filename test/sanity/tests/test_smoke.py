import pytest

# Liveness + wiring. No auth, no data created — runs on every install/upgrade.


@pytest.mark.smoke
def test_ping(client):
    r = client.get("/ping")
    assert r.status_code == 200, r.text


@pytest.mark.smoke
def test_jwks_served(client):
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200, r.text
    keys = r.json().get("keys", [])
    assert keys, "JWKS has no keys"
    assert keys[0].get("kid"), "first JWK has no kid"


@pytest.mark.smoke
def test_openapi_served(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200, r.text
    assert "/consent/v1/validate" in r.json().get("paths", {})
