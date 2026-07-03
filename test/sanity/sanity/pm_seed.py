"""Idempotent seeding of the sanity test partner into Partner Management (PM).

CM no longer stores partner keys, so the signed e2e needs a real partner in PM
whose public key matches the sanity's private key. This module ensures such a
partner exists and is active — creating it once via PM's admin API and then
leaving it in place (persistent test fixture, never deleted).

Flow (all idempotent):
  1. If PM's key-fetch API already serves the (partner_id, kid), we're done.
  2. Otherwise, using a partner_manager admin token, submit an onboarding request
     with the derived public key and approve it → partner active, key active.
  3. If the partner already exists (409) but the key isn't served, submit a
     key-update request for the kid and approve it, and enable the partner.
"""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

import httpx


def public_pem_and_alg(private_pem: str):
    """Derive the SPKI public PEM + JWS algorithm from a PEM private key."""
    priv = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    if isinstance(priv, ed25519.Ed25519PrivateKey):
        alg = "EdDSA"
    elif isinstance(priv, ec.EllipticCurvePrivateKey):
        alg = "ES256"
    elif isinstance(priv, rsa.RSAPrivateKey):
        alg = "RS256"
    else:
        raise ValueError("unsupported private key type for PM seeding")
    return pub_pem, alg


def key_servable(cfg) -> bool:
    """True if PM's fetch API already serves the sanity (partner_id, kid)."""
    if not cfg.pm_partner_api_url:
        return False
    url = f"{cfg.pm_partner_api_url}/keys/{cfg.pm_partner_id}/{cfg.pm_kid}"
    r = httpx.get(url, verify=cfg.verify_tls, timeout=20)
    return r.status_code == 200


def _admin_token(cfg):
    """Obtain a client-credentials token for PM's admin API.

    Prefers dedicated PM admin creds (SANITY_PM_ADMIN_*); otherwise falls back to
    the sanity Keycloak client (SANITY_TOKEN_URL/CLIENT_ID/CLIENT_SECRET) — that
    client must then be granted the `partner_manager` role in the staff realm.
    Returns None only when no credentials are configured at all (PM auth off).
    """
    if cfg.pm_admin_token_url and cfg.pm_admin_client_secret:
        token_url, client_id, client_secret = (
            cfg.pm_admin_token_url, cfg.pm_admin_client_id, cfg.pm_admin_client_secret,
        )
    elif cfg.token_url and cfg.client_secret:
        token_url, client_id, client_secret = (
            cfg.token_url, cfg.client_id, cfg.client_secret,
        )
    else:
        return None
    r = httpx.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        verify=cfg.verify_tls,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(token):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def ensure_seeded(cfg) -> str:
    """Ensure the sanity partner + key exist and are servable in PM.

    Returns "exists" | "onboarded" | "key-added". Raises RuntimeError if seeding
    is impossible (no admin URL) or did not result in a servable key.
    """
    if key_servable(cfg):
        return "exists"
    if not cfg.pm_admin_url:
        raise RuntimeError(
            "PM key not servable and SANITY_PM_ADMIN_URL not set — cannot seed "
            f"partner '{cfg.pm_partner_id}'"
        )

    pub_pem, alg = public_pem_and_alg(cfg.pm_private_key_pem)
    token = _admin_token(cfg)
    admin = cfg.pm_admin_url
    key_input = {"public_key": pub_pem, "kid": cfg.pm_kid, "algorithm": alg}

    # 1. Try a fresh onboarding request.
    r = httpx.post(
        f"{admin}/partners/requests/onboarding",
        headers=_headers(token),
        json={
            "partner_id": cfg.pm_partner_id,
            "name": "CM Sanity Test Partner",
            "org_name": "OpenG2P Consent Manager sanity suite",
            "description": "Persistent test partner for the CM signed-validate e2e. Test only.",
            "keys": [key_input],
        },
        verify=cfg.verify_tls,
        timeout=30,
    )
    outcome = "onboarded"
    if r.status_code == 409:
        # Partner already exists — (re)add the key via a key-update request and
        # make sure the partner is enabled.
        outcome = "key-added"
        httpx.post(
            f"{admin}/partners/{cfg.pm_partner_id}/enable",
            headers=_headers(token), verify=cfg.verify_tls, timeout=20,
        )
        r = httpx.post(
            f"{admin}/partners/requests/key-update",
            headers=_headers(token),
            json={"partner_id": cfg.pm_partner_id, "keys": [key_input]},
            verify=cfg.verify_tls,
            timeout=30,
        )
    if r.status_code in (401, 403):
        raise RuntimeError(
            f"PM admin API rejected the seed ({r.status_code}) at {r.request.url}. "
            f"The seed needs a Keycloak client with the 'partner_manager' role "
            f"(token_sent={token is not None}). Either set SANITY_PM_ADMIN_* to a "
            f"dedicated partner_manager client, or grant the sanity client "
            f"'{cfg.client_id}' the partner_manager role in the staff realm."
        )
    r.raise_for_status()
    request_id = r.json()["id"]

    # 2. Approve the request → partner/key become active.
    a = httpx.post(
        f"{admin}/partners/requests/{request_id}/approve",
        headers=_headers(token),
        json={"notes": "auto-approved by CM sanity seed"},
        verify=cfg.verify_tls,
        timeout=30,
    )
    a.raise_for_status()

    if not key_servable(cfg):
        raise RuntimeError(
            f"seeded partner '{cfg.pm_partner_id}' but key '{cfg.pm_kid}' is still "
            "not servable by PM's fetch API"
        )
    return outcome


def main() -> int:
    """CLI entrypoint (`python -m sanity.pm_seed`) — used by the deploy-time seed
    Job. Idempotent: safe to run on every install/upgrade. Exits 0 on success or
    a benign skip (PM not configured); non-zero only on an unexpected failure."""
    from sanity.config import Config

    cfg = Config.from_env()
    if not cfg.can_reach_pm:
        print("[pm-seed] SANITY_PM_PARTNER_API_URL not set — nothing to seed; skipping")
        return 0
    try:
        status = ensure_seeded(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"[pm-seed] FAILED to seed partner '{cfg.pm_partner_id}': {exc}")
        return 1
    print(f"[pm-seed] partner '{cfg.pm_partner_id}' key '{cfg.pm_kid}': {status}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
