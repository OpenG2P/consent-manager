"""Use-case mode on /validate (G2P-5719, contract §7): a configured receipt
presenter (the Composite) names the use case it serves; the consenting
partner's use-case policy in Partner Management then replaces its per-registry
scope policies."""
import pytest
from test_assisted_consent import (  # noqa: F401 (fixtures)
    approved_consent,
    as_partner,
    portal,
    realm_key,
    upload,
)
from test_exchange import PRESENTER, cfg, exchange_on, post  # noqa: F401 (fixture)
from test_grants import CSR, CSR_SCOPES, FR, FR_SCOPES, GRANTS, bind

USE_CASE = "loan-profile@1"
# The use case's scopes (what the Composite asks each registry for).
USE_CASE_SCOPES = ["farmer_personal_details", "crop_season"]


def ctx(**extra):
    base = {"use_case": USE_CASE, "purpose": "credit-assessment",
            "requested_scopes": USE_CASE_SCOPES}
    base.update(extra)
    return base


@pytest.fixture
def bank(pm, new_partner):
    """A partner granted the use case in the exchange's PM (no scope policies)."""
    p = new_partner()
    pm.grant(p.audience, None, use_cases=[USE_CASE, "name@1"])
    return p


def issue(call, bank, presenter=PRESENTER, claims=None, data_controller=None, **context):
    jws = bank.sign(claims or bank.claims(grants=GRANTS))
    payload = {"consent_jws": jws, "partner_id": presenter, "issue_receipts": True,
               "request_context": ctx(**context)}
    if data_controller:
        payload["data_controller"] = data_controller
    return post(call, payload)


def test_use_case_permit_limits_scopes_to_consent_and_use_case(call, cfg, pm, bank):
    exchange_on(cfg)
    pm.requests.clear()
    body = issue(call, bank)
    assert body["decision"] == "permit", body
    assert set(body["receipts"]) == {FR, CSR}
    # consent grant ∩ requested (the use case's scopes), per registry.
    assert body["grants"] == {FR: ["farmer_personal_details"], CSR: ["crop_season"]}
    # Only the use-case policy was read (data_controller empty).
    assert {r.url.params.get("data_controller") for r in pm.requests} == {""}


def test_use_case_not_granted(call, cfg, bank):
    exchange_on(cfg)
    body = issue(call, bank, use_case="crop-insurance@1")
    assert body["decision"] == "deny" and body["reason_code"] == "use_case_not_granted"
    assert body["receipts"] is None


def test_use_case_mode_needs_requested_scopes(call, cfg, bank):
    """Without the use case's scopes the whole consent would pass: denied."""
    exchange_on(cfg)
    body = issue(call, bank, requested_scopes=[])
    assert body["decision"] == "deny" and body["reason_code"] == "scope_exceeds_policy"


def test_use_case_purpose_must_match_consent(call, cfg, bank):
    exchange_on(cfg)
    body = issue(call, bank, purpose="marketing")
    assert body["decision"] == "deny" and body["reason_code"] == "purpose_not_allowed"


def test_use_case_policy_purposes_subject_types_and_validity_apply(call, cfg, pm, bank):
    exchange_on(cfg)
    pm.grant(bank.audience, None, use_cases=[USE_CASE], allowed_purposes=["insurance"])
    assert issue(call, bank)["reason_code"] == "purpose_not_allowed"
    pm.grant(bank.audience, None, use_cases=[USE_CASE], allowed_subject_id_types=["PHONE"])
    assert issue(call, bank)["reason_code"] == "subject_not_allowed"
    pm.grant(bank.audience, None, use_cases=[USE_CASE], max_validity_duration="P7D")
    assert issue(call, bank)["reason_code"] == "validity_exceeds_policy"
    pm.grant(bank.audience, None, use_cases=[USE_CASE], allowed_signing_algs=["ES256"])
    assert issue(call, bank)["reason_code"] == "signature_invalid"
    version = pm.grant(bank.audience, None, use_cases=[USE_CASE])
    body = issue(call, bank, data_controller=FR)
    assert body["decision"] == "permit" and body["policy_version"] == version


def test_partner_without_use_case_policy_is_unknown(call, cfg, pm, new_partner):
    exchange_on(cfg)
    p = new_partner()
    bind(pm, p, FR, FR_SCOPES)  # a scope policy only
    body = issue(call, p)
    assert body["decision"] == "deny" and body["reason_code"] == "unknown_partner"
    assert "use-case policy" in body["detail"]


def test_stored_decision_is_not_reused_for_another_use_case(call, cfg, bank):
    exchange_on(cfg)
    claims = bank.claims(grants=GRANTS)
    assert issue(call, bank, claims=claims)["decision"] == "permit"
    again = issue(call, bank, claims=claims, use_case="crop-insurance@1")
    assert again["reason_code"] == "use_case_not_granted"


def test_use_case_ignored_for_a_caller_that_is_not_a_presenter(call, cfg, bank):
    """Only a configured presenter switches to use-case mode: any other caller
    gets the partner's scope policies (none here)."""
    exchange_on(cfg)
    jws = bank.sign(bank.claims(grants=GRANTS))
    body = post(call, {"consent_jws": jws, "data_controller": FR,
                       "partner_id": bank.audience, "request_context": ctx()})
    assert body["decision"] == "deny" and body["reason_code"] == "unknown_partner"


def test_without_use_case_the_exchange_uses_scope_policies(call, cfg, pm, bank):
    exchange_on(cfg)
    bind(pm, bank, FR, ["farmer_personal_details"])
    bind(pm, bank, CSR, CSR_SCOPES)
    jws = bank.sign(bank.claims(grants=GRANTS))
    body = post(call, {"consent_jws": jws, "partner_id": PRESENTER, "issue_receipts": True})
    assert body["decision"] == "permit", body
    assert body["grants"] == {FR: ["farmer_personal_details"], CSR: sorted(CSR_SCOPES)}


def test_stored_consent_in_use_case_mode(call, cfg, portal, as_partner, pm, upload,  # noqa: F811
                                         new_partner):
    p = new_partner()
    bind(pm, p, FR, ["farmer_personal_details"])
    bind(pm, p, CSR, CSR_SCOPES)
    # A scope-policy consent, made before the exchange role is on (at the
    # Exchange consents are made by use case).
    consent_id = approved_consent(call, as_partner(p.audience), upload)
    exchange_on(cfg)
    ask = {"consent_id": consent_id, "consent_partner_id": p.audience,
           "partner_id": PRESENTER, "issue_receipts": True}

    # No use-case policy yet.
    assert post(call, {**ask, "request_context": ctx()})["reason_code"] == "unknown_partner"
    pm.grant(p.audience, None, use_cases=[USE_CASE])
    body = post(call, {**ask, "request_context": ctx()})
    assert body["decision"] == "permit", body
    assert body["grants"] == {FR: ["farmer_personal_details"], CSR: ["crop_season"]}
    assert set(body["receipts"]) == {FR, CSR}
    assert post(call, {**ask, "request_context": ctx(use_case="x@1")})[
        "reason_code"] == "use_case_not_granted"
    assert post(call, {**ask, "request_context": ctx(purpose="marketing")})[
        "reason_code"] == "purpose_not_allowed"
