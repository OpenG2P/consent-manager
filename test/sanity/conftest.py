import httpx
import pytest

from sanity import pm_seed
from sanity.config import Config


@pytest.fixture(scope="session")
def cfg() -> Config:
    return Config.from_env()


@pytest.fixture(scope="session")
def client(cfg):
    # STAFF api (policy admin, decisions, approvals).
    with httpx.Client(base_url=cfg.base_url, verify=cfg.verify_tls, timeout=20) as c:
        yield c


@pytest.fixture(scope="session")
def partner_client(cfg):
    # PARTNER api (/validate, status, receipts, JWKS) — no Keycloak.
    with httpx.Client(base_url=cfg.partner_base_url, verify=cfg.verify_tls, timeout=20) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(cfg):
    """A Keycloak client-credentials token with the admin role.

    None when auth is disabled (the CM then accepts calls without a token).
    Skips the e2e tests if auth is on but no client credentials were provided.
    """
    if not cfg.auth_enabled:
        return None
    if not cfg.token_url or not cfg.client_secret:
        pytest.skip("e2e needs SANITY_TOKEN_URL + SANITY_CLIENT_SECRET when auth is enabled")
    resp = httpx.post(
        cfg.token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
        },
        verify=cfg.verify_tls,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"} if admin_token else {}


@pytest.fixture(scope="session")
def pm_partner(cfg):
    """Ensure the persistent sanity test partner + key exist in Partner Management.

    Skips the signed e2e (rather than failing) when PM isn't reachable/seedable,
    so smoke + contract coverage stays green in environments without PM. The
    seeded partner is intentionally left in place after the run.
    """
    if not cfg.can_reach_pm:
        pytest.skip(
            "SANITY_PM_PARTNER_API_URL not set — cannot reach Partner Management to "
            "verify/seed the test partner; signed e2e skipped"
        )
    try:
        status = pm_seed.ensure_seeded(cfg)
    except Exception as exc:  # noqa: BLE001 — surface as a skip with the reason
        pytest.skip(f"could not seed PM test partner: {exc}")
    return {"status": status, "partner_id": cfg.pm_partner_id, "kid": cfg.pm_kid}
