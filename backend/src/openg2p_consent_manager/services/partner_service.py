import logging
from dataclasses import dataclass
from typing import Optional

from openg2p_fastapi_common.service import BaseService

from ..config import Settings
from .pm_policy_client import PmPolicyClient, pm_partner_id

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


@dataclass(frozen=True)
class PartnerRef:
    """The partner a policy is for. ``audience`` is what the partner presents as
    ``aud`` (and what records store as ``partner_id``); ``partner_mgmt_id`` its
    Partner Management id (keys and policies); ``controller_id`` the registry
    the policy is for (None for a use-case policy); ``use_case`` the use case a
    use-case policy is for (None for a scope policy)."""

    audience: str
    controller_id: Optional[str]
    partner_mgmt_id: str
    use_case: Optional[str] = None


class PartnerService(BaseService):
    """Partners and their access policies, both owned by Partner Management.
    The Consent Manager keeps no partner records: it reads the partner's active
    policy for a data controller (or for a use case) from PM, cached."""

    def __init__(self, name="", **kwargs):
        super().__init__(name, **kwargs)
        self.policies = PmPolicyClient.get_component()

    async def get_verification_material(
        self, audience: str, controller_id: Optional[str], use_case: Optional[str] = None
    ) -> Optional[dict]:
        """The partner's active policy from Partner Management, for the
        validation hot path: its use-case policy for ``use_case`` when given,
        else its scope policy for ``controller_id``.

        Partner public keys are not included: the shared fastapi-common
        CryptoHelper fetches them from PM by ``partner_mgmt_id``.

        Shape: {"partner": PartnerRef, "policy": PmPolicy}; None when PM has no
        active policy (unknown or inactive partner, or no policy for it — for a
        use case: the use case is not granted).
        Raises PolicyUnavailable when PM cannot be reached and nothing usable is
        cached (fail closed)."""
        if not audience:
            return None
        if use_case:
            policy = await self.policies.get_use_case_policy(audience, use_case)
        else:
            policy = await self.policies.get_policy(audience, controller_id)
        if policy is None:
            return None
        partner = PartnerRef(
            audience=audience,
            controller_id=None if use_case else (controller_id or None),
            partner_mgmt_id=pm_partner_id(audience),
            use_case=use_case or None,
        )
        return {"partner": partner, "policy": policy}

    async def scope_policies(self, audience: str) -> list:
        """The partner's active scope policies (one per data controller), by
        controller. Raises PolicyUnavailable."""
        policies = await self.policies.list_policies(audience)
        return sorted(
            (p for p in policies if p.data_controller), key=lambda p: p.data_controller
        )

    async def use_case_policies(self, audience: str) -> list:
        """The partner's active use-case policies (one per use case), by use
        case. Raises PolicyUnavailable."""
        policies = await self.policies.list_policies(audience)
        return sorted((p for p in policies if p.use_case), key=lambda p: p.use_case)
