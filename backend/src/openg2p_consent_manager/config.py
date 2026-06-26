from openg2p_fastapi_common.config import Settings as BaseSettings
from pydantic_settings import SettingsConfigDict

from . import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="consent_manager_", env_file=".env", extra="allow"
    )

    openapi_title: str = "OpenG2P Consent Manager"
    openapi_description: str = """
        Consent Manager for OpenG2P.

        Acts as the Policy Decision Point (PDP) for outbound data sharing: it
        verifies partner-signed consent objects against each partner's onboarded
        policy and returns the effective set of fields a data holder (PEP) may
        release. Also issues canonical consent artefacts and signed receipts.
        """
    openapi_version: str = __version__

    # ── Database ────────────────────────────────────────────────────────────
    db_driver: str = "postgresql+asyncpg"
    db_username: str = "postgres"
    db_password: str = "postgres"
    db_hostname: str = "localhost"
    db_port: int = 5432
    db_dbname: str = "consent_manager_db"

    # Pooling is handled by openg2p-fastapi-common's async engine. For horizontal
    # scaling the app is fully stateless: scale by adding pods/workers and ensure
    # Postgres max_connections ≳ (pods × workers × pool_size + headroom).

    # ── Signing / trust ─────────────────────────────────────────────────────
    # CM receipt signing key (PEM). Provide via env/secret in production.
    # If unset, a process-local ephemeral key is generated (dev only).
    cm_signing_private_key_pem: str = ""
    cm_signing_kid: str = "cm-2025-01"
    cm_signing_algorithm: str = "EdDSA"  # EdDSA (ed25519) | ES256 | RS256

    # Identifier of this data controller / registry tenant. Consent objects must
    # carry this value as their data_controller for the audience check to pass.
    controller_id: str = "openg2p.registry"

    # Replay window for embedded consent objects (seconds). issued_at must be
    # within now ± this skew.
    replay_freshness_window_sec: int = 300

    # ── OIDC (origination flow ID-token validation) ─────────────────────────
    # If oidc_jwks_url is set, ID tokens are signature-verified against the IdP
    # JWKS. Otherwise claims are read unverified (dev only) and token_validated
    # is recorded as false.
    oidc_jwks_url: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""

    # ── Hot-path caching (pod-local, TTL) ───────────────────────────────────
    # Partner keys and policies change rarely but are read on every validate.
    # Cached in-process per pod; staleness bounded by the TTL.
    partner_cache_ttl_sec: int = 60
    partner_cache_enabled: bool = True
