import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sanity.signing import new_keypair, sign_object, verify_receipt_signature

# Full PDP round-trip: onboard a self-contained TEST_SANITY partner, sign a
# consent object as that partner, and exercise permit + the key denials, then
# verify the CM's receipt signature against its JWKS. Gated by SANITY_RUN_E2E.

SCOPES = ["farmer_profile.basic", "farmer_profile.crops"]


@pytest.mark.e2e
def test_validate_roundtrip(client, cfg, auth_headers):
    if not cfg.run_e2e:
        pytest.skip("SANITY_RUN_E2E not enabled")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    aud = f"TEST_SANITY_AUD_{ts}_{uuid.uuid4().hex[:6]}"
    kid = "sanity-key-1"
    priv, pem = new_keypair()

    # 1. onboard partner + key + policy (self-contained controller/audience)
    r = client.post("/consent/v1/partners", headers=auth_headers, json={
        "name": f"TEST_SANITY {ts}", "org_name": "Sanity Suite",
        "audience": aud, "controller_id": cfg.controller_id,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    try:
        r = client.post(f"/consent/v1/partners/{pid}/keys", headers=auth_headers, json={
            "kid": kid, "algorithm": "EdDSA", "public_key": pem,
        })
        assert r.status_code == 201, r.text

        r = client.put(f"/consent/v1/partners/{pid}/policy", headers=auth_headers, json={
            "allowed_data_scopes": SCOPES,
            "allowed_purposes": ["share_farm_profile"],
            "allowed_subject_id_types": ["national_id"],
            "allowed_signing_algs": ["EdDSA"],
            "max_validity_duration": "P1Y", "fetch_type": "oneshot",
        })
        assert r.status_code == 200, r.text

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
            obj["signature"] = sign_object(obj, priv, kid)
            return obj

        # 2. permit — request a subset; effective = consented ∩ policy ∩ requested
        obj = signed_object(SCOPES + ["farmer_profile.landholdings"])
        r = client.post("/consent/v1/validate", headers=auth_headers, json={
            "consent_object": obj, "partner_id": pid,
            "request_context": {"requested_scopes": SCOPES},
        })
        assert r.status_code == 200, r.text
        dec = r.json()
        assert dec["decision"] == "permit", dec
        assert set(dec["effective_data_scopes"]) == set(SCOPES), dec
        receipt_id = dec["receipt_id"]

        # 3. the CM receipt is signed by the CM key — verify against its JWKS
        receipt = client.get(f"/consent/v1/receipts/{receipt_id}").json()
        jwks = client.get("/.well-known/jwks.json").json()
        sig = receipt["signature"]
        msg = receipt["consent_artefact"]["hash"].encode("utf-8")
        assert verify_receipt_signature(
            jwks, sig["kid"], sig["algorithm"], msg, sig["value"]
        ), "CM receipt signature did not verify against the published JWKS"

        # 4. denial — tampered signature
        bad = signed_object(["farmer_profile.basic"])
        bad["data_scopes"] = ["farmer_profile.crops"]  # mutate AFTER signing
        d = client.post("/consent/v1/validate", headers=auth_headers, json={
            "consent_object": bad, "partner_id": pid,
        }).json()
        assert d["decision"] == "deny" and d["reason_code"] == "signature_invalid", d

        # 5. denial — scope outside policy
        over = signed_object(["farmer_profile.landholdings"])
        d = client.post("/consent/v1/validate", headers=auth_headers, json={
            "consent_object": over, "partner_id": pid,
        }).json()
        assert d["decision"] == "deny" and d["reason_code"] == "scope_exceeds_policy", d

    finally:
        # cleanup — no DELETE endpoint; suspend the test partner so it's inert.
        client.patch(f"/consent/v1/partners/{pid}", headers=auth_headers,
                     json={"status": "suspended"})
