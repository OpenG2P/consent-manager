"""Which policy changes widen access (and so need approval)."""

from types import SimpleNamespace

import pytest

from openg2p_consent_manager.services.partner_service import PartnerService


def _policy(**overrides):
    base = dict(
        allowed_data_scopes=["farmer-registry.land"],
        allowed_purposes=["credit-assessment"],
        allowed_subject_id_types=["FAYDA_FAN"],
        allowed_signing_algs=["ES256"],
        max_validity_duration="P90D",
        data_life="P1Y",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_first_policy_widens():
    assert PartnerService._is_widening(_policy(), None)


def test_identical_policy_does_not_widen():
    assert not PartnerService._is_widening(_policy(), _policy())


@pytest.mark.parametrize("field", ["allowed_purposes", "allowed_subject_id_types", "allowed_signing_algs"])
def test_clearing_an_any_when_empty_list_widens(field):
    assert PartnerService._is_widening(_policy(**{field: []}), _policy())


@pytest.mark.parametrize("field", ["allowed_purposes", "allowed_subject_id_types", "allowed_signing_algs"])
def test_restricting_an_any_list_does_not_widen(field):
    assert not PartnerService._is_widening(_policy(), _policy(**{field: []}))


def test_clearing_data_scopes_narrows():
    assert not PartnerService._is_widening(_policy(allowed_data_scopes=[]), _policy())


def test_adding_a_value_widens():
    assert PartnerService._is_widening(
        _policy(allowed_purposes=["credit-assessment", "insurance"]), _policy()
    )
