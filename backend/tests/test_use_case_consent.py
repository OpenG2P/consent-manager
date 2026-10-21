"""Consent by use case at the Exchange (exchange role).

A partner at the Exchange has a use-case policy in Partner Management (no scope
policies). Consents made through the partner portal (assisted) or the
lifecycle API name a granted use case; the grants and purpose are the
Composite's use case (here a fake Composite behind an httpx transport). The
stored consent is then presentable by the Composite only for that use case.
"""
import httpx
import jwt
import pytest
from test_assisted_consent import (  # noqa: F401 (fixtures)
    PRESENTER,
    STAFF,
    as_partner,
    portal,
    realm_key,
    upload,
)
from test_exchange import cfg, exchange_on, post  # noqa: F401 (fixture)
from test_grants import CSR, FR

USE_CASE = "loan-profile@1"
OTHER = "crop-insurance@1"
COMPOSITE_URL = "http://composite.test"
SUBJECT = {"type": "FAYDA_FAN", "value": "123456789012"}


def describe(ref, purpose="credit-assessment", scopes=None):
    """A use case as the Composite's GET /composite/v1/use-cases/{ref} answers."""
    scopes = scopes or {
        FR: {"required": ["farmer_personal_details"], "optional": []},
        CSR: {"required": ["crop_season"], "optional": ["measures"]},
    }
    name = ref.split("@")[0]
    return {
        "use_case": ref, "name": name, "version": "1.0.0", "status": "published",
        "title": f"Title of {name}", "description": "", "purpose": purpose,
        "input": {"subject": {"id_types": ["FAYDA_FAN", "FARMER_ID"]}},
        "consent_grants_needed": sorted(scopes), "consent_scopes": scopes,
    }


class FakeComposite:
    def __init__(self):
        self.use_cases = {}
        self.down = False

    def handler(self, request):
        if self.down:
            raise httpx.ConnectError("Composite is down", request=request)
        prefix = "/composite/v1/use-cases/"
        ref = request.url.path[len(prefix):]
        if ref in self.use_cases:
            return httpx.Response(200, json=self.use_cases[ref])
        return httpx.Response(404, json={"error": {"code": "unknown_use_case"}})


@pytest.fixture
def composite(env):
    from openg2p_consent_manager.config import Settings
    from openg2p_consent_manager.services import CompositeClient

    config = Settings.get_config()
    saved = config.composite_api_url
    config.composite_api_url = COMPOSITE_URL
    fake = FakeComposite()
    fake.use_cases = {USE_CASE: describe(USE_CASE), OTHER: describe(OTHER)}
    client = CompositeClient.get_component()
    client.transport = httpx.MockTransport(fake.handler)
    client.invalidate()
    yield fake
    config.composite_api_url = saved
    client.transport = None
    client.invalidate()


@pytest.fixture
def exchange(cfg, portal, composite):  # noqa: F811
    exchange_on(cfg)
    return composite


@pytest.fixture
def bank(pm, new_partner):
    """A partner at the Exchange: a use-case policy only."""
    p = new_partner()
    pm.grant_use_cases(p.audience, [USE_CASE, OTHER])
    return p


def create(pc, **extra):
    body = {"subject_id": SUBJECT, "use_case": USE_CASE}
    body.update(extra)
    return pc("POST", "/consent-requests", json=body)


def approve_assisted(call, pc, upload, **extra):  # noqa: F811
    status, req = create(pc, **extra)
    assert status == 201, req
    assert upload(pc, req["id"])[0] == 201
    assert pc("POST", f"/consent-requests/{req['id']}/submit")[0] == 200
    return req, call("POST", f"{STAFF}/{req['id']}/approve", json={"note": "ok"})


def present(call, consent_id, audience, use_case=USE_CASE, scopes=None):
    return post(call, {
        "consent_id": consent_id, "consent_partner_id": audience,
        "partner_id": PRESENTER, "issue_receipts": True,
        "request_context": {
            "subject_id": SUBJECT, "use_case": use_case, "purpose": "credit-assessment",
            "requested_scopes": scopes or ["farmer_personal_details", "crop_season", "measures"],
        },
    })


# ── partner portal ───────────────────────────────────────────────────────────


def test_access_lists_granted_use_cases(exchange, as_partner, pm, new_partner):
    p = new_partner()
    pm.grant_use_cases(p.audience, [USE_CASE, "gone@2"], max_validity_duration="P6M")
    pm.grant(p.audience, None, use_case=OTHER, allowed_purposes=["insurance"])
    pc = as_partner(p.audience)
    status, access = pc("GET", "/access")
    assert status == 200, access
    assert access["consent_by"] == "use_case" and access["scope_policies"] == []
    by = {u["use_case"]: u for u in access["use_cases"]}
    loan = by[USE_CASE]
    assert loan["available"] and loan["purpose"] == "credit-assessment"
    assert loan["title"] == "Title of loan-profile"
    assert {g["data_controller"]: g["data_scopes"] for g in loan["grants"]} == {
        FR: ["farmer_personal_details"], CSR: ["crop_season", "measures"]}
    csr = next(g for g in loan["grants"] if g["data_controller"] == CSR)
    assert csr["required_scopes"] == ["crop_season"] and csr["optional_scopes"] == ["measures"]
    assert loan["max_validity_duration"] == "P6M" and loan["policy_version"] == 1
    assert by["gone@2"]["available"] is False and "not published" in by["gone@2"]["detail"]
    # One entry per use-case policy, each with its own limits.
    assert sorted(by) == sorted([USE_CASE, "gone@2", OTHER])
    assert by[OTHER]["allowed_purposes"] == ["insurance"]
    assert by[OTHER]["max_validity_duration"] == "P1Y"
    assert pc("GET", "/request-settings")[1]["consent_by"] == "use_case"


def test_access_without_use_case_policy_is_empty(exchange, as_partner, new_partner):
    status, access = as_partner(new_partner().audience)("GET", "/access")
    assert status == 200 and access == {"consent_by": "use_case", "scope_policies": [],
                                        "use_cases": []}


def test_portal_consent_by_use_case_and_validate(call, exchange, as_partner, bank, upload):  # noqa: F811
    pc = as_partner(bank.audience)
    req, (status, verified) = approve_assisted(call, pc, upload)
    assert req["use_case"] == USE_CASE and req["purpose"] == {"code": "credit-assessment"}
    assert {g["data_controller"]: g["data_scopes"] for g in req["grants"]} == {
        FR: ["farmer_personal_details"], CSR: ["crop_season", "measures"]}
    assert status == 200, verified
    consent_id = verified["consent_id"]
    status, consent = pc("GET", f"/consents/{consent_id}")
    assert consent["use_case"] == USE_CASE
    assert {g["data_controller"]: g["effective_data_scopes"] for g in consent["grants"]} == {
        FR: ["farmer_personal_details"], CSR: ["crop_season", "measures"]}

    body = present(call, consent_id, bank.audience)
    assert body["decision"] == "permit", body
    assert body["grants"] == {FR: ["farmer_personal_details"],
                              CSR: ["crop_season", "measures"]}
    assert set(body["receipts"]) == {FR, CSR}

    # Granted to the partner too, but the consent was given for loan-profile@1.
    other = present(call, consent_id, bank.audience, use_case=OTHER)
    assert other["decision"] == "deny" and other["reason_code"] == "use_case_not_granted"
    assert USE_CASE in other["detail"] and OTHER in other["detail"]


def test_exchange_refuses_requests_with_grants(call, exchange, as_partner, bank):
    """At the Exchange a consent request must name a use case: explicit grants
    (with or without use_case) are refused, portal and lifecycle alike."""
    pc = as_partner(bank.audience)
    grants = [{"data_controller": FR, "data_scopes": ["farmer_personal_details"]}]
    purpose = {"code": "credit-assessment"}
    for extra in ({"grants": grants, "purpose": purpose},
                  {"grants": grants, "purpose": purpose, "use_case": None}):
        status, body = create(pc, **extra)
        assert status == 400 and "made for a use case" in body["error"], body
    status, body = call("POST", "/consent/v1/consent-requests", json={
        "subject_id": SUBJECT, "partner_id": bank.audience, "purpose": purpose,
        "grants": grants})
    assert status == 400 and "made for a use case" in body["error"], body
    status, body = call("POST", "/consent/v1/consent-requests", json={
        "subject_id": SUBJECT, "partner_id": bank.audience, "purpose": purpose,
        "data_controller": FR, "requested_scopes": ["farmer_personal_details"]})
    assert status == 400 and "made for a use case" in body["error"], body


def test_portal_use_case_not_granted(exchange, as_partner, bank):
    status, body = create(as_partner(bank.audience), use_case="soil-health@1")
    assert status == 422 and "use_case_not_granted" in body["error"]


def test_portal_use_case_checks(exchange, as_partner, pm, bank):
    pc = as_partner(bank.audience)
    status, body = create(pc, use_case="loan-profile")
    assert status == 422 and "name@major" in body["error"]
    status, body = create(pc, purpose={"code": "marketing"})
    assert status == 422 and "is not the purpose of use case" in body["error"]
    exchange.use_cases.pop(OTHER)
    status, body = create(pc, use_case=OTHER)
    assert status == 422 and "not published" in body["error"]
    pm.grant_use_cases(bank.audience, [USE_CASE], allowed_subject_id_types=["PHONE"])
    status, body = create(pc)
    assert status == 422 and "subject_not_allowed" in body["error"]
    pm.grant_use_cases(bank.audience, [USE_CASE], max_validity_duration="P7D")
    status, body = create(pc, validity={"valid_until": "2099-01-01T00:00:00Z"})
    assert status == 422 and "validity_exceeds_policy" in body["error"]


def test_composite_down_fails_closed(call, exchange, as_partner, bank, upload):  # noqa: F811
    pc = as_partner(bank.audience)
    status, req = create(pc)
    assert status == 201, req
    assert upload(pc, req["id"])[0] == 201
    assert pc("POST", f"/consent-requests/{req['id']}/submit")[0] == 200

    from openg2p_consent_manager.services import CompositeClient

    CompositeClient.get_component().invalidate()
    exchange.down = True
    status, body = pc("GET", "/access")
    assert status == 503 and "Composite" in body["error"]
    status, body = create(pc)
    assert status == 503 and "Composite" in body["error"]
    status, body = call("POST", f"{STAFF}/{req['id']}/approve", json={"note": "ok"})
    assert status == 503 and "Composite" in body["error"]


def test_composite_not_configured_fails_closed(exchange, as_partner, bank):
    from openg2p_consent_manager.config import Settings

    Settings.get_config().composite_api_url = ""
    status, body = create(as_partner(bank.audience))
    assert status == 503


def test_approval_narrows_to_the_use_case_now(call, exchange, as_partner, pm, bank, upload):  # noqa: F811
    pc = as_partner(bank.audience)
    status, req = create(pc)
    assert upload(pc, req["id"])[0] == 201
    assert pc("POST", f"/consent-requests/{req['id']}/submit")[0] == 200
    # The use case drops `measures` before staff approve.
    from openg2p_consent_manager.services import CompositeClient

    exchange.use_cases[USE_CASE] = describe(USE_CASE, scopes={
        FR: {"required": ["farmer_personal_details"], "optional": []},
        CSR: {"required": ["crop_season"], "optional": []},
    })
    CompositeClient.get_component().invalidate()
    status, verified = call("POST", f"{STAFF}/{req['id']}/approve", json={"note": "ok"})
    assert status == 200, verified
    status, consent = pc("GET", f"/consents/{verified['consent_id']}")
    assert {g["data_controller"]: g["effective_data_scopes"] for g in consent["grants"]} == {
        FR: ["farmer_personal_details"], CSR: ["crop_season"]}


def test_approval_needs_the_use_case_still_granted(call, exchange, as_partner, pm, bank, upload):  # noqa: F811
    pc = as_partner(bank.audience)
    status, req = create(pc)
    assert upload(pc, req["id"])[0] == 201
    assert pc("POST", f"/consent-requests/{req['id']}/submit")[0] == 200
    pm.revoke(bank.audience, use_case=USE_CASE)
    status, body = call("POST", f"{STAFF}/{req['id']}/approve", json={"note": "ok"})
    assert status == 422 and "use_case_not_granted" in body["error"]


def test_portal_outside_exchange_role_keeps_scope_requests(portal, composite, as_partner, bank):
    """Not the exchange role: use_case is a label and grants are required."""
    status, body = create(as_partner(bank.audience))
    assert status == 422 and "'grants' is required" in body["error"]


# ── lifecycle API ────────────────────────────────────────────────────────────


def test_lifecycle_consent_by_use_case(call, exchange, bank):
    status, req = call("POST", "/consent/v1/consent-requests", json={
        "subject_id": SUBJECT, "partner_id": bank.audience, "use_case": USE_CASE})
    assert status == 201, req
    assert req["use_case"] == USE_CASE and req["purpose"] == {"code": "credit-assessment"}
    token = jwt.encode({"sub": SUBJECT["value"]}, "k" * 32, algorithm="HS256")
    call("POST", f"/consent/v1/consent-requests/{req['id']}/authenticate",
         json={"id_token": token})
    status, art = call("POST", f"/consent/v1/consent-requests/{req['id']}/approve",
                       json={"granted_scopes": ["farmer_personal_details", "crop_season"]})
    assert status == 201, art
    assert art["use_case"] == USE_CASE
    assert {g["data_controller"]: g["effective_data_scopes"] for g in art["grants"]} == {
        FR: ["farmer_personal_details"], CSR: ["crop_season"]}
    assert present(call, art["consent_id"], bank.audience)["decision"] == "permit"
    assert present(call, art["consent_id"], bank.audience, use_case=OTHER)[
        "reason_code"] == "use_case_not_granted"


def test_lifecycle_use_case_shape_and_role(call, cfg, composite, bank):  # noqa: F811
    status, body = call("POST", "/consent/v1/consent-requests", json={
        "subject_id": SUBJECT, "partner_id": bank.audience, "use_case": USE_CASE})
    assert status == 422 and "exchange role" in body["error"]
    exchange_on(cfg)
    status, body = call("POST", "/consent/v1/consent-requests", json={
        "subject_id": SUBJECT, "partner_id": bank.audience, "use_case": USE_CASE,
        "grants": [{"data_controller": FR, "data_scopes": ["farmer_personal_details"]}]})
    assert status == 400, body
    status, body = call("POST", "/consent/v1/consent-requests", json={
        "subject_id": SUBJECT, "partner_id": bank.audience, "use_case": "soil-health@1"})
    assert status == 422 and "use_case_not_granted" in body["error"]
