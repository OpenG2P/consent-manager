import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sanity.signing import load_private_key_pem, sign_object, verify_receipt_signature

# Full PDP round-trip. Partner signing keys now live in the Partner Management
# (PM) service — CM fetches them at validate time and can no longer self-inject a
# key. So the e2e onboards a CM partner whose ``partner_mgmt_id`` points at a
# PM-seeded test partner, signs a consent object with the matching private key
# (supplied via SANITY_PM_* env), and exercises permit + the key denials, then
# verifies the CM receipt against its JWKS. Gated by SANITY_RUN_E2E and by the
# presence of PM signing material.

SCOPES = ["farmer_profile.basic", "farmer_profile.crops"]


@pytest.mark.e2e
def test_validate_roundtrip(client, partner_client, cfg, auth_headers, pm_partner):
    # client = STAFF api (policy admin); partner_client = PARTNER api (/validate,
    # receipts, JWKS — no Keycloak).
    if not cfg.run_e2e:
        pytest.skip("SANITY_RUN_E2E not enabled")

    # pm_partner fixture has ensured PM serves cfg.pm_partner_id / cfg.pm_kid.
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    aud = f"TEST_SANITY_AUD_{ts}_{uuid.uuid4().hex[:6]}"
    kid = cfg.pm_kid
    priv = load_private_key_pem(cfg.pm_private_key_pem)

    # 1. onboard a CM partner bound to the PM test partner + policy.
    r = client.post("/consent/v1/partners", headers=auth_headers, json={
        "name": f"TEST_SANITY {ts}",
        "audience": aud, "controller_id": cfg.controller_id,
        "partner_mgmt_id": cfg.pm_partner_id,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    try:
        r = client.put(f"/consent/v1/partners/{pid}/policy", headers=auth_headers, json={
            "allowed_data_scopes": SCOPES,
            "allowed_purposes": ["share_farm_profile"],
            "allowed_subject_id_types": ["national_id"],
            "allowed_signing_algs": ["EdDSA", "ES256", "RS256"],
            "max_validity_duration": "P1Y", "fetch_type": "oneshot",
        })
        # AWE-aware: if approval gating is ON, this first (widening) policy either
        # went `pending` (awaiting a human — the permit round-trip can't run), or
        # the AWE submit failed (AWE enabled but not fully configured). In both
        # cases the signed round-trip is out of scope for an unattended test.
        if r.status_code == 502 and "awe_submit_failed" in r.text:
            pytest.skip(f"AWE approval enabled but submit failed (AWE not fully configured): {r.text}")
        assert r.status_code == 200, r.text
        if r.json().get("status") == "pending":
            assert r.json().get("awe_request_id"), r.json()
            pytest.skip("AWE approval enabled — policy is pending human approval; permit round-trip skipped")

        now = datetime.now(timezone.utc)

        def signed_object(scopes):
            obj = {
                "@context": "https://openg2p.org/contexts/consent_object.jsonld",
                "@type": "ConsentObject",
                "jti": uuid.uuid4().hex,
                "subject_id": {"type": "national_id", "value": "FARMER_1234"},
                "data_controller": cfg.controller_id, "aud": aud,
                "purpose": {"code": "share_farm_profile", "text": "sanity"},
                "data_scopes": scopes, "fetch_type": "oneshot",
                "validity": {
                    "valid_from": now.isoformat(),
                    "valid_until": (now + timedelta(days=30)).isoformat(),
                },
                "issued_at": now.isoformat(),
            }
            # The PM-registered key's algorithm is inferred from the loaded key.
            obj["signature"] = sign_object(obj, priv, kid, algorithm=_alg_for(priv))
            return obj

        # 2. permit — request a subset; effective = consented ∩ policy ∩ requested
        obj = signed_object(SCOPES + ["farmer_profile.landholdings"])
        r = partner_client.post("/consent/v1/validate", json={
            "consent_object": obj, "partner_id": pid,
            "request_context": {"requested_scopes": SCOPES},
        })
        assert r.status_code == 200, r.text
        dec = r.json()
        assert dec["decision"] == "permit", dec
        assert set(dec["effective_data_scopes"]) == set(SCOPES), dec
        receipt_id = dec["receipt_id"]

        # 3. the CM receipt is signed by the CM key — verify against its JWKS
        receipt = partner_client.get(f"/consent/v1/receipts/{receipt_id}").json()
        jwks = partner_client.get("/.well-known/jwks.json").json()
        sig = receipt["signature"]
        msg = receipt["consent_artefact"]["hash"].encode("utf-8")
        assert verify_receipt_signature(
            jwks, sig["kid"], sig["algorithm"], msg, sig["value"]
        ), "CM receipt signature did not verify against the published JWKS"

        # 4. denial — tampered signature
        bad = signed_object(["farmer_profile.basic"])
        bad["data_scopes"] = ["farmer_profile.crops"]  # mutate AFTER signing
        d = partner_client.post("/consent/v1/validate", json={
            "consent_object": bad, "partner_id": pid,
        }).json()
        assert d["decision"] == "deny" and d["reason_code"] == "signature_invalid", d

        # 5. denial — scope outside policy
        over = signed_object(["farmer_profile.landholdings"])
        d = partner_client.post("/consent/v1/validate", json={
            "consent_object": over, "partner_id": pid,
        }).json()
        assert d["decision"] == "deny" and d["reason_code"] == "scope_exceeds_policy", d

    finally:
        # cleanup — no DELETE endpoint; suspend the test partner so it's inert.
        client.patch(f"/consent/v1/partners/{pid}", headers=auth_headers,
                     json={"status": "suspended"})


def _alg_for(priv) -> str:
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

    if isinstance(priv, ed25519.Ed25519PrivateKey):
        return "EdDSA"
    if isinstance(priv, ec.EllipticCurvePrivateKey):
        return "ES256"
    if isinstance(priv, rsa.RSAPrivateKey):
        return "RS256"
    raise ValueError("unsupported private key type for sanity signing")
