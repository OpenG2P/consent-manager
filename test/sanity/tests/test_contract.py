import pytest

# Contract: auth is actually enforced. Skipped when the CM runs with auth off.


@pytest.mark.contract
def test_validate_requires_auth(client, cfg):
    if not cfg.auth_enabled:
        pytest.skip("auth disabled")
    r = client.post("/consent/v1/validate", json={})
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"


@pytest.mark.contract
def test_admin_requires_auth(client, cfg):
    if not cfg.auth_enabled:
        pytest.skip("auth disabled")
    r = client.post(
        "/consent/v1/partners",
        json={"name": "x", "org_name": "x", "audience": "x", "controller_id": "x"},
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"


@pytest.mark.contract
def test_subject_requires_auth(client, cfg):
    if not cfg.auth_enabled:
        pytest.skip("auth disabled")
    r = client.get("/consent/v1/my/consents")
    assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"
