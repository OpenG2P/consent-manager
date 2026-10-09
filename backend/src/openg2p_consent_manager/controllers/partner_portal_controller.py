import logging
from typing import Literal, Optional

from fastapi import Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from openg2p_fastapi_common.controller import BaseController

from ..auth import PartnerUser, current_partner_user
from ..config import Settings
from ..schemas.portal import (
    AssistedRequestCreate,
    AssistedRequestDetail,
    AssistedRequestList,
    AssistedRequestResponse,
    EvidenceResponse,
    PartnerBindingView,
    PartnerConsentList,
    PartnerConsentResponse,
    PartnerMe,
)
from ..services import (
    AssistedConsentService,
    ConsentService,
    EvidenceError,
    LifecycleError,
)
from .assisted_views import (
    consent_view,
    error,
    evidence_list,
    file_response,
    not_found,
    request_fields,
)

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


class PartnerPortalController(BaseController):
    """Partner portal API (consent scenario 1) — partner users from the
    Keycloak ``partner`` realm. Every call is scoped to the token's
    ``partner_id``; another partner's request or consent is 404. Disabled (404)
    while the partner realm is not configured."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.assisted = AssistedConsentService.get_component()
        self.consents = ConsentService.get_component()
        self.router.prefix += "/consent/v1/partner-portal"
        self.router.tags += ["Partner portal"]

        def route(path, endpoint, method, model=None, status_code=200):
            self.router.add_api_route(
                path, endpoint, methods=[method], status_code=status_code,
                responses={status_code: {"model": model}} if model else None,
            )

        route("/me", self.me, "GET", PartnerMe)
        route("/bindings", self.bindings, "GET", list[PartnerBindingView])
        route("/consent-requests", self.create_request, "POST", AssistedRequestResponse, 201)
        route("/consent-requests", self.list_requests, "GET", AssistedRequestList)
        route("/consent-requests/{request_id}", self.get_request, "GET", AssistedRequestDetail)
        route(
            "/consent-requests/{request_id}/evidence", self.upload_evidence, "POST",
            EvidenceResponse, 201,
        )
        route(
            "/consent-requests/{request_id}/evidence/{evidence_id}", self.download_evidence,
            "GET",
        )
        route(
            "/consent-requests/{request_id}/evidence/{evidence_id}", self.delete_evidence,
            "DELETE", status_code=204,
        )
        route(
            "/consent-requests/{request_id}/submit", self.submit, "POST",
            AssistedRequestResponse,
        )
        route(
            "/consent-requests/{request_id}/cancel", self.cancel, "POST",
            AssistedRequestResponse,
        )
        route("/consents", self.list_consents, "GET", PartnerConsentList)
        route("/consents/{consent_id}", self.get_consent, "GET", PartnerConsentResponse)
        route("/consents/{consent_id}/receipt", self.get_receipt, "GET")

    async def _request_response(self, req) -> AssistedRequestResponse:
        ids = await self.assisted.consent_ids([req.id])
        return AssistedRequestResponse(**request_fields(req, ids.get(req.id)))

    async def me(self, user: PartnerUser = Depends(current_partner_user)) -> PartnerMe:
        return PartnerMe(
            username=user.username, name=user.name, partner_id=user.partner_id,
            roles=user.roles,
        )

    async def bindings(self, user: PartnerUser = Depends(current_partner_user)):
        return [PartnerBindingView(**b) for b in await self.assisted.bindings(user.partner_id)]

    async def create_request(
        self, data: AssistedRequestCreate, user: PartnerUser = Depends(current_partner_user),
    ):
        try:
            req = await self.assisted.create_request(user.partner_id, user.username, data)
        except LifecycleError as exc:
            return error(exc.status_code, exc.detail)
        return JSONResponse(
            status_code=201,
            content=AssistedRequestResponse(**request_fields(req)).model_dump(mode="json"),
        )

    async def list_requests(
        self,
        user: PartnerUser = Depends(current_partner_user),
        status: Optional[str] = Query(None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> AssistedRequestList:
        total, rows = await self.assisted.list_requests(
            audience=user.partner_id, status=status, limit=limit, offset=offset
        )
        ids = await self.assisted.consent_ids([r.id for r in rows])
        return AssistedRequestList(
            total=total,
            items=[AssistedRequestResponse(**request_fields(r, ids.get(r.id))) for r in rows],
        )

    async def get_request(
        self, request_id: str, user: PartnerUser = Depends(current_partner_user)
    ):
        req = await self.assisted.get_request(request_id, user.partner_id)
        if req is None:
            return not_found()
        ids = await self.assisted.consent_ids([req.id])
        return AssistedRequestDetail(
            **request_fields(req, ids.get(req.id)),
            evidence=evidence_list(await self.assisted.list_evidence(req.id)),
        )

    async def upload_evidence(
        self,
        request_id: str,
        file: UploadFile = File(...),
        kind: str = Form("signed_form"),
        user: PartnerUser = Depends(current_partner_user),
    ):
        # Read at most one byte over the limit: enough to reject an oversize file.
        data = await file.read(_config.evidence_max_bytes + 1)
        try:
            evidence = await self.assisted.add_evidence(
                request_id, user.partner_id, user.username, data,
                file.content_type, file.filename, kind,
            )
        except (LifecycleError, EvidenceError) as exc:
            return error(exc.status_code, exc.detail)
        return JSONResponse(
            status_code=201,
            content=EvidenceResponse.model_validate(evidence).model_dump(mode="json"),
        )

    async def download_evidence(
        self, request_id: str, evidence_id: str,
        user: PartnerUser = Depends(current_partner_user),
    ):
        evidence = await self.assisted.get_evidence(request_id, evidence_id, user.partner_id)
        if evidence is None:
            return not_found()
        try:
            data = await self.assisted.evidence_bytes(evidence)
        except EvidenceError as exc:
            return error(exc.status_code, exc.detail)
        return file_response(evidence, data)

    async def delete_evidence(
        self, request_id: str, evidence_id: str,
        user: PartnerUser = Depends(current_partner_user),
    ):
        try:
            await self.assisted.delete_evidence(request_id, evidence_id, user.partner_id)
        except LifecycleError as exc:
            return error(exc.status_code, exc.detail)
        return Response(status_code=204)

    async def submit(self, request_id: str, user: PartnerUser = Depends(current_partner_user)):
        try:
            req = await self.assisted.submit(request_id, user.partner_id)
        except LifecycleError as exc:
            return error(exc.status_code, exc.detail)
        return await self._request_response(req)

    async def cancel(self, request_id: str, user: PartnerUser = Depends(current_partner_user)):
        try:
            req = await self.assisted.cancel(request_id, user.partner_id)
        except LifecycleError as exc:
            return error(exc.status_code, exc.detail)
        return await self._request_response(req)

    async def list_consents(
        self,
        user: PartnerUser = Depends(current_partner_user),
        status: Optional[Literal["active", "revoked", "expired"]] = Query(None),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> PartnerConsentList:
        total, rows, use_cases = await self.assisted.list_consents(
            user.partner_id, status, limit, offset
        )
        return PartnerConsentList(total=total, items=[consent_view(a, use_cases) for a in rows])

    async def get_consent(
        self, consent_id: str, user: PartnerUser = Depends(current_partner_user)
    ):
        artefact, use_cases = await self.assisted.get_consent(user.partner_id, consent_id)
        if artefact is None:
            return not_found()
        return consent_view(artefact, use_cases)

    async def get_receipt(
        self, consent_id: str, user: PartnerUser = Depends(current_partner_user)
    ):
        artefact, _ = await self.assisted.get_consent(user.partner_id, consent_id)
        if artefact is None:
            return not_found()
        receipt = await self.consents.get_receipt_by_consent(consent_id)
        if receipt is None:
            return not_found()
        return JSONResponse(content=receipt.document)
