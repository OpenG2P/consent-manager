import logging
from typing import Optional

from fastapi import Query
from fastapi.responses import JSONResponse
from openg2p_fastapi_common.controller import BaseController

from ..config import Settings
from ..schemas.partner import (
    KeyCreate,
    KeyResponse,
    PartnerCreate,
    PartnerResponse,
    PartnerUpdate,
    PolicyResponse,
    PolicyUpsert,
)
from ..services import PartnerService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)

_NOT_FOUND = JSONResponse(status_code=404, content={"error": "not_found"})


class PartnerController(BaseController):
    """Administrative partner onboarding, key, and policy management."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.partners = PartnerService.get_component()
        self.router.prefix += "/consent/v1/partners"
        self.router.tags += ["Partners & Policy"]

        self.router.add_api_route(
            "", self.create_partner,
            responses={201: {"model": PartnerResponse}}, methods=["POST"], status_code=201,
        )
        self.router.add_api_route(
            "/{partner_id}", self.get_partner,
            responses={200: {"model": PartnerResponse}}, methods=["GET"],
        )
        self.router.add_api_route(
            "/{partner_id}", self.update_partner,
            responses={200: {"model": PartnerResponse}}, methods=["PATCH"],
        )
        self.router.add_api_route(
            "/{partner_id}/keys", self.add_key,
            responses={201: {"model": KeyResponse}}, methods=["POST"], status_code=201,
        )
        self.router.add_api_route(
            "/{partner_id}/keys/{kid}", self.revoke_key, methods=["DELETE"], status_code=204,
        )
        self.router.add_api_route(
            "/{partner_id}/policy", self.upsert_policy,
            responses={200: {"model": PolicyResponse}}, methods=["PUT"],
        )
        self.router.add_api_route(
            "/{partner_id}/policy", self.get_policy,
            responses={200: {"model": PolicyResponse}}, methods=["GET"],
        )

    async def create_partner(self, data: PartnerCreate) -> PartnerResponse:
        partner = await self.partners.create_partner(data)
        return PartnerResponse.model_validate(partner)

    async def get_partner(self, partner_id: str):
        partner = await self.partners.get_partner(partner_id)
        if partner is None:
            return _NOT_FOUND
        return PartnerResponse.model_validate(partner)

    async def update_partner(self, partner_id: str, data: PartnerUpdate):
        partner = await self.partners.update_partner(partner_id, data)
        if partner is None:
            return _NOT_FOUND
        return PartnerResponse.model_validate(partner)

    async def add_key(self, partner_id: str, data: KeyCreate):
        key = await self.partners.add_key(partner_id, data)
        if key is None:
            return _NOT_FOUND
        return KeyResponse.model_validate(key)

    async def revoke_key(self, partner_id: str, kid: str):
        ok = await self.partners.revoke_key(partner_id, kid)
        if not ok:
            return _NOT_FOUND
        return JSONResponse(status_code=204, content=None)

    async def upsert_policy(self, partner_id: str, data: PolicyUpsert):
        policy = await self.partners.upsert_policy(partner_id, data)
        if policy is None:
            return _NOT_FOUND
        return PolicyResponse.model_validate(policy)

    async def get_policy(self, partner_id: str, version: Optional[int] = Query(None)):
        policy = await self.partners.get_policy(partner_id, version)
        if policy is None:
            return _NOT_FOUND
        return PolicyResponse.model_validate(policy)
