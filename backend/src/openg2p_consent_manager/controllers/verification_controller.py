import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import Body, Depends, Query
from fastapi.responses import JSONResponse
from openg2p_fastapi_common.controller import BaseController
from pydantic import ValidationError

from ..auth import current_identity, require_role
from ..config import Settings
from ..schemas.common import ReasonCode, StatusResponse
from ..schemas.verification import Decision, DecisionLogResponse, ValidateRequest
from ..services import ConsentService, VerificationService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


class VerificationController(BaseController):
    """Primary PDP endpoints — the registry/PEP hot path."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.verification = VerificationService.get_component()
        self.consents = ConsentService.get_component()
        self.router.prefix += "/consent/v1"
        self.router.tags += ["Verification"]

        # The PEP (registry) calls these with a Keycloak service token. The
        # consent object's own signature is the application-layer proof on top.
        svc = [Depends(current_identity)]
        self.router.add_api_route(
            "/validate", self.validate, dependencies=svc,
            responses={200: {"model": Decision}}, methods=["POST"],
        )
        self.router.add_api_route(
            "/consents/{consent_id}/status", self.get_status, dependencies=svc,
            responses={200: {"model": StatusResponse}}, methods=["GET"],
        )
        # Receipt fetch is public — the signature makes it self-verifying.
        self.router.add_api_route(
            "/receipts/{receipt_id}", self.get_receipt, methods=["GET"],
        )
        # Recent decisions — admin status/audit view for the console.
        self.router.add_api_route(
            "/decisions", self.list_decisions,
            dependencies=[Depends(require_role(_config.auth_admin_role))],
            responses={200: {"model": list[DecisionLogResponse]}}, methods=["GET"],
        )

    async def validate(self, payload: dict = Body(...)) -> Decision:
        # Parse defensively so a malformed object is a clean deny, not a 422.
        try:
            parsed = ValidateRequest(**payload)
        except ValidationError as exc:
            _logger.info("Malformed consent object: %s", exc)
            return Decision(
                decision="deny", reason_code=ReasonCode.malformed_object,
                detail="consent object failed schema validation",
                evaluated_at=datetime.now(timezone.utc),
            )
        raw_consent_object = payload.get("consent_object", {})
        return await self.verification.validate(parsed, raw_consent_object)

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

    async def list_decisions(
        self,
        partner_id: Optional[str] = Query(None),
        decision: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=200),
    ):
        rows = await self.verification.list_decisions(
            partner_id=partner_id, decision=decision, limit=limit
        )
        return [DecisionLogResponse.model_validate(r) for r in rows]
