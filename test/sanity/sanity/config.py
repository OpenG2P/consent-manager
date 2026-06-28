import os
from dataclasses import dataclass


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    base_url: str          # CM service base, e.g. http://consent-manager-api (no path prefix)
    verify_tls: bool
    run_e2e: bool          # run the data-creating round-trip
    fail_on_error: bool    # propagate pytest exit code (CD gating) — handled in entrypoint
    auth_enabled: bool     # whether the CM enforces Keycloak auth
    token_url: str         # Keycloak token endpoint (e2e + auth)
    client_id: str         # client-credentials client (has CONSENT_MANAGER_ADMIN)
    client_secret: str
    controller_id: str     # controller/module used for the self-contained test partner

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            base_url=(os.environ.get("SANITY_BASE_URL") or "http://localhost:8000").rstrip("/"),
            verify_tls=_bool(os.environ.get("SANITY_VERIFY_TLS"), True),
            run_e2e=_bool(os.environ.get("SANITY_RUN_E2E"), False),
            fail_on_error=_bool(os.environ.get("SANITY_FAIL_ON_ERROR"), False),
            auth_enabled=_bool(os.environ.get("SANITY_AUTH_ENABLED"), True),
            token_url=os.environ.get("SANITY_TOKEN_URL", ""),
            client_id=os.environ.get("SANITY_CLIENT_ID", "consent-manager"),
            client_secret=os.environ.get("SANITY_CLIENT_SECRET", ""),
            controller_id=os.environ.get("SANITY_CONTROLLER_ID", "sanity-controller"),
        )
