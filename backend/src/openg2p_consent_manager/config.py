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
    # CM receipt signing key. Preferred source is a PKCS#12 (.p12) keystore
    # holding the private key (+ certificate). Falls back to a PEM string, then
    # to a process-local ephemeral key (dev only). The signing algorithm is
    # auto-detected from the loaded key type (Ed25519→EdDSA, EC→ES256, RSA→RS256).
    cm_signing_p12_path: str = ""
    cm_signing_p12_password: str = ""
    cm_signing_private_key_pem: str = ""
    cm_signing_kid: str = "cm-2025-01"
    cm_signing_algorithm: str = "EdDSA"  # fallback hint only; key type wins

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

    # ── Caller authentication (Keycloak / OIDC bearer) ──────────────────────
    # Validates bearer tokens on protected endpoints against the Keycloak JWKS,
    # exactly like the AWE service. When auth_enabled is false (dev), tokens are
    # accepted without verification and role checks pass.
    auth_enabled: bool = True
    auth_issuer: str = ""  # e.g. https://keycloak.../realms/staff
    auth_jwks_url: str = ""  # usually issuer + /protocol/openid-connect/certs
    auth_audience: str = ""  # optional; empty disables the audience check
    auth_algorithms: list[str] = ["RS256", "ES256", "EdDSA"]
    # Role (realm- or client-scoped) required for partner/policy admin endpoints.
    auth_admin_role: str = "CONSENT_MANAGER_ADMIN"
    # Default subject id-type when a token omits the subject_id_type claim.
    subject_default_id_type: str = "national_id"
