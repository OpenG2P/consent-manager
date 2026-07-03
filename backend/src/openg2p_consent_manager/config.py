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
    # Set true by the Helm chart in demo mode so the service warns loudly that it
    # is signing with the public bundled demo key (must be replaced for production).
    cm_signing_is_demo: bool = False

    # NOTE: the data controller / module is a per-partner attribute
    # (Partner.controller_id), set at onboarding — one shared CM serves many
    # modules. A consent object's data_controller is validated against the
    # onboarded partner's controller_id, so there is no single global controller.

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
    # The partner row + its active policy change rarely but are read on every
    # validate. Cached in-process per pod; staleness bounded by the TTL. (Keys
    # are NOT part of this — they live in Partner Management, see below.)
    partner_cache_ttl_sec: int = 60
    partner_cache_enabled: bool = True

    # ── Partner public keys (Partner Management service) ────────────────────
    # Partner signing keys are no longer stored in CM. They are owned by the
    # Partner Management (PM) service and fetched from its unauthenticated
    # key-fetch API: GET {partner_mgmt_api_url}/keys/{reference_id}. CM caches
    # them per pod with the discipline PM's Cache-Control implies. A partner's
    # PM reference is Partner.partner_mgmt_id (falling back to Partner.audience).
    #
    # Empty partner_mgmt_api_url disables PM fetching — verification then fails
    # closed (no keys → deny), which is the correct safe default until wired.
    partner_mgmt_api_url: str = ""  # e.g. http://partner-management-partner-api:8000
    # Soft TTL: refresh window. Bounds how long a rotated/revoked key stays
    # trusted. Capped by the response's Cache-Control max-age when smaller.
    partner_key_cache_ttl_seconds: int = 300
    # Hard TTL: during a PM outage, serve last-known-good keys up to this age,
    # then fail closed.
    partner_key_hard_ttl_seconds: int = 21600
    # Negative cache: remember a 404 ("no keys") briefly to avoid hammering PM
    # for a disabled/unknown partner on every request.
    partner_key_negative_ttl_seconds: int = 30
    # Minimum interval between forced refetches for one partner (throttles the
    # unknown-kid refresh that catches key rotation immediately).
    partner_key_refresh_cooldown_seconds: int = 10
    # HTTP timeout (seconds) for a single key fetch from PM.
    partner_key_fetch_timeout_seconds: float = 3.0

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

    # ── Approval Workflow Engine (AWE) integration ──────────────────────────
    # Partner onboarding (and, later, policy-widening) is gated behind human
    # approval in the shared, per-environment AWE. CM is a *caller service*: it
    # submits an approval request on onboarding and flips the partner to active
    # only when AWE delivers a terminal `request_approved` webhook. Approvals
    # themselves happen in AWE's own UI — CM never renders an approver inbox.
    #
    # When awe_enabled is false (default), onboarding is immediate (status
    # active, approval_status not_required) — unchanged legacy behaviour.
    awe_enabled: bool = False
    # Base URL of the environment's AWE, reachable from CM pods (e.g.
    # https://awe.<baseDomain>). No trailing slash needed.
    awe_base_url: str = ""
    awe_http_timeout_seconds: float = 30.0
    # AWE policy that governs partner onboarding. Registered in AWE out-of-band.
    awe_partner_onboarding_policy_key: str = "consent-manager.partner_onboarding.v1"
    # CM→AWE service auth: Keycloak client-credentials. The fetched bearer is
    # sent on POST /v1/awe/requests. If awe_static_token is set it is used
    # verbatim instead (dev/testing).
    awe_token_url: str = ""  # Keycloak token endpoint
    awe_client_id: str = ""
    awe_client_secret: str = ""
    awe_static_token: str = ""
    # Per-caller callback secret CM registered into the shared AWE DB. AWE looks
    # the raw secret up by this id; CM holds the same raw secret to verify the
    # HMAC on inbound webhooks. `callback_secret_id` is passed on every request.
    awe_callback_secret_id: str = ""
    awe_callback_hmac_secret: str = ""
    # Public URL AWE should POST terminal webhooks back to. Must resolve to
    # CM's /consent/v1/awe/webhooks/decision endpoint.
    awe_callback_url: str = ""
    # Reject webhooks whose signed timestamp is more than this far from now.
    awe_webhook_max_skew_sec: int = 300
