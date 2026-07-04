import logging
from datetime import datetime, timezone

from fastapi import Body
from fastapi.responses import JSONResponse
from openg2p_fastapi_common.controller import BaseController
from pydantic import ValidationError

from ..config import Settings
from ..schemas.common import ReasonCode, StatusResponse
from ..schemas.verification import Decision, ValidateRequest
from ..services import ConsentService, VerificationService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


class VerificationController(BaseController):
    """PARTNER-api PDP endpoints — the registry/PEP hot path.

    Trust is NOT Keycloak: it's the partner-signed consent object, verified inside
    ``validate`` against the partner's keys from Partner Management (replay-guarded
    by ``jti``). The partner api carries no Keycloak realm; registry↔CM is secured
    at the transport layer (Istio mTLS / network policy).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.verification = VerificationService.get_component()
        self.consents = ConsentService.get_component()
        self.router.prefix += "/consent/v1"
        self.router.tags += ["Verification"]

        self.router.add_api_route(
            "/validate", self.validate,
            responses={200: {"model": Decision}}, methods=["POST"],
        )
        self.router.add_api_route(
            "/consents/{consent_id}/status", self.get_status,
            responses={200: {"model": StatusResponse}}, methods=["GET"],
        )
        # Receipt fetch is public — the signature makes it self-verifying.
        self.router.add_api_route(
            "/receipts/{receipt_id}", self.get_receipt, methods=["GET"],
        )

    async def validate(self, payload: dict = Body(...)) -> Decision:
        # Parse defensively so a malformed request is a clean deny, not a 422.
        # The consent object itself is a compact JWS (consent_jws); its claims
        # and signature are validated inside the verification service.
        try:
            parsed = ValidateRequest(**payload)
        except ValidationError as exc:
            _logger.info("Malformed validate request: %s", exc)
            return Decision(
                decision="deny", reason_code=ReasonCode.malformed_object,
                detail="validate request failed schema validation",
                evaluated_at=datetime.now(timezone.utc),
            )
        return await self.verification.validate(parsed)

    async def get_status(self, consent_id: str):
        result = await self.consents.get_status(consent_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        return StatusResponse(**result)

    async def get_receipt(self, receipt_id: str):
        receipt = await self.consents.get_receipt(receipt_id)
        if receipt is None:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        return JSONResponse(content=receipt.document)
