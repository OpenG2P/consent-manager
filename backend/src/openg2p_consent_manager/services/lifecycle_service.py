import hashlib
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

import jwt
from openg2p_fastapi_common.service import BaseService

from ..config import Settings
from ..db import async_session
from ..models import (
    ArtefactSource,
    ArtefactStatus,
    AuthContext,
    ConsentArtefact,
    ConsentRequest,
    RequestStatus,
)
from ..utils.canonical import iso_duration_to_timedelta
from .composite_client import (
    EXCHANGE_NEEDS_USE_CASE,
    USE_CASE_REF,
    CompositeClient,
    CompositeUnavailable,
    consent_by_use_case,
)
from .partner_service import PartnerService
from .pm_policy_client import PolicyUnavailable, common_policy_fields, policy_fields
from .receipt_service import ReceiptService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class LifecycleError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class LifecycleService(BaseService):
    """Origination flow: request → authenticate → approve / deny."""

    def __init__(self, name="", **kwargs):
        super().__init__(name, **kwargs)
        self.partners = PartnerService.get_component()
        self.receipts = ReceiptService.get_component()
        self.composite = CompositeClient.get_component()

    async def create_request(self, data) -> ConsentRequest:
        """``partner_id`` is the partner's audience. Each requested grant (or the
        single ``data_controller`` + ``requested_scopes``) must be within the
        partner's active policy for that controller in Partner Management.

        Exchange role: the request must name a ``use_case`` and is made for it
        — its grants and purpose are the Composite's use case, within the
        partner's policy for that use case (see ``resolve_use_case``)."""
        if consent_by_use_case() and data.use_case is None:
            raise LifecycleError(400, EXCHANGE_NEEDS_USE_CASE)
        if data.use_case is not None:
            return await self._create_use_case_request(data)
        if data.grants is not None:
            requested = data.grants
        else:
            requested = [
                SimpleNamespace(
                    data_controller=data.data_controller, data_scopes=data.requested_scopes
                )
            ]
        resolved = await self.resolve_grants(data.partner_id, requested)
        if data.grants is not None:
            # One request, several controllers.
            grants = [g for g, _ in resolved]
            requested_scopes = sorted({s for g in grants for s in g["data_scopes"]})
            controller_id = grants[0]["data_controller"] if len(grants) == 1 else None
        else:
            grants = None
            requested_scopes = data.requested_scopes
            controller_id = data.data_controller

        validity = data.validity or {}
        async with async_session()() as session:
            req = ConsentRequest(
                subject_id_type=data.subject_id.type,
                subject_id_value=data.subject_id.value,
                controller_id=controller_id,
                partner_id=data.partner_id,
                purpose=data.purpose,
                requested_scopes=requested_scopes,
                grants=grants,
                valid_from=validity.get("valid_from"),
                valid_until=validity.get("valid_until"),
                status=RequestStatus.pending.value,
            )
            session.add(req)
            await session.commit()
            await session.refresh(req)
            return req

    async def _create_use_case_request(self, data) -> ConsentRequest:
        if not consent_by_use_case():
            raise LifecycleError(
                422, "use_case is for the exchange role: give the grants instead"
            )
        validity = data.validity or {}
        purpose_code = (data.purpose or {}).get("code") if data.purpose else None
        use_case, _, grants = await self.resolve_use_case(
            data.partner_id, data.use_case, data.subject_id.type, purpose_code,
            validity.get("valid_from"), validity.get("valid_until"),
        )
        async with async_session()() as session:
            req = ConsentRequest(
                subject_id_type=data.subject_id.type,
                subject_id_value=data.subject_id.value,
                controller_id=grants[0]["data_controller"] if len(grants) == 1 else None,
                partner_id=data.partner_id,
                purpose={"code": use_case.purpose},
                requested_scopes=sorted({s for g in grants for s in g["data_scopes"]}),
                grants=grants,
                valid_from=validity.get("valid_from"),
                valid_until=validity.get("valid_until"),
                status=RequestStatus.pending.value,
                use_case=use_case.ref,
            )
            session.add(req)
            await session.commit()
            await session.refresh(req)
            return req

    # ── Exchange role: consent by use case ──────────────────────────────────

    async def use_case_policy(self, audience: str, ref: str):
        """The partner's policy for use case ``ref`` in Partner Management, or
        None (not granted). Raises LifecycleError(503) when PM cannot be
        reached."""
        try:
            material = await self.partners.get_verification_material(
                audience, None, use_case=ref
            )
        except PolicyUnavailable as exc:
            raise LifecycleError(
                503, "the partner's policy could not be read from Partner Management"
            ) from exc
        return material["policy"] if material else None

    async def read_use_case(self, ref: str):
        """The Composite's published use case ``ref``. Raises LifecycleError:
        503 when the Composite cannot be reached (fail closed), 422 when it
        publishes no such use case or one a consent cannot be made for."""
        try:
            use_case = await self.composite.get_use_case(ref)
        except CompositeUnavailable as exc:
            raise LifecycleError(
                503,
                f"the Composite could not be reached to read use case '{ref}'; "
                "a consent by use case cannot be made now",
            ) from exc
        if use_case is None:
            raise LifecycleError(422, f"use case '{ref}' is not published on the Composite")
        if use_case.unscoped_controllers or not use_case.grants:
            raise LifecycleError(
                422,
                f"use case '{ref}' does not name the scopes it needs from "
                f"{', '.join(use_case.unscoped_controllers) or 'any registry'}: "
                "a consent cannot be made for it",
            )
        if not use_case.purpose:
            raise LifecycleError(
                422, f"use case '{ref}' names no purpose: a consent cannot be made for it"
            )
        return use_case

    async def granted_use_case(self, audience: str, ref: str):
        """(the use case's policy, use case) when the partner has a policy for
        ``ref`` in Partner Management. Raises LifecycleError (422
        use_case_not_granted; 503)."""
        if not ref or not USE_CASE_REF.match(ref):
            raise LifecycleError(422, "use_case must be name@major, e.g. loan-profile@1")
        policy = await self.use_case_policy(audience, ref)
        if policy is None:
            raise LifecycleError(
                422,
                f"use_case_not_granted: use case '{ref}' is not granted to the partner "
                "in Partner Management",
            )
        return policy, await self.read_use_case(ref)

    async def resolve_use_case(
        self, audience: str, ref: str, subject_id_type: str,
        purpose_code: Optional[str] = None, valid_from=None, valid_until=None,
    ):
        """A consent for use case ``ref``: granted by the partner's policy for
        that use case; its grants (controller → the use case's scopes) and purpose are
        the Composite's use case; the policy's purposes, subject ID types and
        maximum validity apply. Returns (use case, policy, grants)."""
        policy, use_case = await self.granted_use_case(audience, ref)
        if purpose_code and purpose_code != use_case.purpose:
            raise LifecycleError(
                422,
                f"purpose '{purpose_code}' is not the purpose of use case '{ref}' "
                f"('{use_case.purpose}')",
            )
        if policy.allowed_purposes and use_case.purpose not in policy.allowed_purposes:
            raise LifecycleError(
                422, f"purpose_not_allowed: '{use_case.purpose}' by the use case's policy"
            )
        if (
            policy.allowed_subject_id_types
            and subject_id_type not in policy.allowed_subject_id_types
        ):
            raise LifecycleError(
                422, f"subject_not_allowed: '{subject_id_type}' by the use case's policy"
            )
        if valid_until is not None and policy.max_validity_duration:
            try:
                limit = iso_duration_to_timedelta(policy.max_validity_duration)
            except ValueError:
                limit = None
            start = _aware(valid_from) if valid_from else datetime.now(timezone.utc)
            if limit is not None and _aware(valid_until) - start > limit:
                raise LifecycleError(422, "validity_exceeds_policy: by the use case's policy")
        grants = [
            {
                "data_controller": g["data_controller"],
                "data_scopes": list(g["data_scopes"]),
                **policy_fields(policy),
                # Marks a grant made by use case (approval narrows to it).
                "use_case": use_case.ref,
            }
            for g in use_case.grants
        ]
        return use_case, policy, grants

    async def use_case_ceiling(self, req):
        """For approving a request made by use case (exchange role): (use-case
        policy, {controller: the use case's scopes now}); the use case must
        still be granted. None for any other request (whose use_case, if any,
        is a label)."""
        if not req.use_case or not any(
            g.get("use_case") == req.use_case for g in req.grants or []
        ):
            return None
        policy, use_case = await self.granted_use_case(
            req.partner_audience or req.partner_id, req.use_case
        )
        return policy, {g["data_controller"]: set(g["data_scopes"]) for g in use_case.grants}

    async def current_policy(self, audience: str, controller: Optional[str]):
        """The partner's active policy for ``controller`` in Partner Management,
        or None. Raises LifecycleError(503) when PM cannot be reached."""
        try:
            material = await self.partners.get_verification_material(audience, controller)
        except PolicyUnavailable as exc:
            raise LifecycleError(
                503, "the partner's policy could not be read from Partner Management"
            ) from exc
        return material["policy"] if material else None

    async def resolve_grants(self, audience: str, requested) -> list:
        """Check each requested grant (``data_controller`` + ``data_scopes``)
        against the partner's active policy for that controller in Partner
        Management. Returns ``[(grant dict, policy)]``; raises LifecycleError."""
        resolved = []
        for g in requested:
            policy = await self.current_policy(audience, g.data_controller)
            if policy is None:
                raise LifecycleError(
                    422,
                    f"no active policy in Partner Management for data_controller "
                    f"'{g.data_controller}'",
                )
            if not set(g.data_scopes).issubset(set(policy.allowed_data_scopes or [])):
                raise LifecycleError(
                    422, f"scope_exceeds_policy for data_controller '{g.data_controller}'"
                )
            resolved.append(
                (
                    {
                        "data_controller": g.data_controller,
                        "data_scopes": list(g.data_scopes),
                        **policy_fields(policy),
                    },
                    policy,
                )
            )
        return resolved

    async def get_request(self, request_id: str) -> Optional[ConsentRequest]:
        async with async_session()() as session:
            return await session.get(ConsentRequest, request_id)

    async def authenticate(self, request_id: str, id_token: str) -> AuthContext:
        async with async_session()() as session:
            req = await session.get(ConsentRequest, request_id)
            if req is None:
                raise LifecycleError(404, "consent request not found")
            if req.status != RequestStatus.pending.value:
                raise LifecycleError(409, f"request is '{req.status}'")

            claims, validated = self._decode_id_token(id_token)
            # Subject identity in the token must match the request's subject.
            sub = claims.get("subject_id_value") or claims.get("sub")
            if sub and sub != req.subject_id_value:
                raise LifecycleError(403, "token subject does not match request")

            ctx = AuthContext(
                consent_request_id=request_id,
                auth_provider=claims.get("iss"),
                auth_method=(claims.get("amr") or [None])[0]
                if isinstance(claims.get("amr"), list)
                else claims.get("amr"),
                auth_timestamp=datetime.now(timezone.utc),
                issuer=claims.get("iss"),
                id_token_hash=hashlib.sha256(id_token.encode("utf-8")).hexdigest(),
                token_validated=validated,
                verified_claims=claims,
            )
            session.add(ctx)
            await session.commit()
            await session.refresh(ctx)
            return ctx

    async def approve(
        self, request_id: str, granted_scopes: Optional[list] = None,
        granted_grants: Optional[list] = None,
    ) -> ConsentArtefact:
        """Approve a request. ``granted_scopes`` for a single-controller request;
        ``granted_grants`` (list of ConsentGrant) for a grants request — the
        subject approves each controller's scopes, and an omitted controller is
        declined. The resulting artefact holds the approved grants.

        An originated consent is presentable at /validate by its ID
        (``consent_id``)."""
        async with async_session()() as session:
            req = await session.get(ConsentRequest, request_id)
            if req is None:
                raise LifecycleError(404, "consent request not found")
            if req.status != RequestStatus.pending.value:
                raise LifecycleError(409, f"request is '{req.status}'")

            ctx = await self._latest_auth_context(session, request_id)
            if ctx is None:
                raise LifecycleError(412, "authentication required before approval")

            if req.grants is not None:
                artefact = await self._approve_grants(
                    session, req, ctx, granted_scopes, granted_grants
                )
                await session.commit()
                await session.refresh(artefact)
                return artefact

            if granted_scopes is None:
                raise LifecycleError(400, "granted_scopes is required for this request")
            if not set(granted_scopes).issubset(set(req.requested_scopes or [])):
                raise LifecycleError(400, "granted scopes exceed requested scopes")

            policy = await self.current_policy(req.partner_id, req.controller_id)
            allowed = set(policy.allowed_data_scopes or []) if policy else set()
            effective = sorted(set(granted_scopes) & allowed)
            if not effective:
                raise LifecycleError(400, "no granted scope permitted by policy")

            now = datetime.now(timezone.utc)
            valid_from = req.valid_from or now
            valid_until = req.valid_until or (now + timedelta(days=365))

            artefact = ConsentArtefact(
                subject_id_type=req.subject_id_type,
                subject_id_value=req.subject_id_value,
                controller_id=req.controller_id,
                partner_id=req.partner_id,
                purpose=req.purpose,
                data_scopes=req.requested_scopes,
                effective_data_scopes=effective,
                fetch_type=policy.fetch_type if policy else "oneshot",
                valid_from=valid_from,
                valid_until=valid_until,
                source=ArtefactSource.originated.value,
                **policy_fields(policy),
                auth_context_id=ctx.id,
                consent_request_id=req.id,
                status=ArtefactStatus.active.value,
            )
            receipt = self.receipts.build_receipt(artefact)
            req.status = RequestStatus.approved.value
            session.add(artefact)
            session.add(receipt)
            await session.commit()
            await session.refresh(artefact)
            return artefact

    async def deny(self, request_id: str, reason: Optional[str]) -> ConsentRequest:
        async with async_session()() as session:
            req = await session.get(ConsentRequest, request_id)
            if req is None:
                raise LifecycleError(404, "consent request not found")
            if req.status != RequestStatus.pending.value:
                raise LifecycleError(409, f"request is '{req.status}'")
            req.status = RequestStatus.denied.value
            await session.commit()
            await session.refresh(req)
            return req

    async def _approve_grants(self, session, req, ctx, granted_scopes, granted_grants):
        """Build (and add to the session) the artefact + receipt for a grants
        request. Each approved grant is narrowed to the partner's active policy
        for its controller."""
        requested = {g["data_controller"]: g for g in req.grants}
        if granted_grants is not None:
            approved = {}
            for g in granted_grants:
                if g.data_controller not in requested:
                    raise LifecycleError(
                        400, f"data_controller '{g.data_controller}' was not requested"
                    )
                if not set(g.data_scopes).issubset(
                    set(requested[g.data_controller]["data_scopes"])
                ):
                    raise LifecycleError(
                        400,
                        f"granted scopes exceed requested scopes for "
                        f"'{g.data_controller}'",
                    )
                approved[g.data_controller] = list(g.data_scopes)
        else:
            # One scope list for every controller: each grant keeps the scopes it
            # requested that the subject approved.
            if not set(granted_scopes).issubset(set(req.requested_scopes or [])):
                raise LifecycleError(400, "granted scopes exceed requested scopes")
            approved = {
                c: [s for s in g["data_scopes"] if s in set(granted_scopes)]
                for c, g in requested.items()
            }

        grants = []
        fetch_type = None
        # A request made for a use case (exchange role) is narrowed to the use
        # case's scopes as they are now, not to scope policies.
        ceiling = await self.use_case_ceiling(req)
        for controller, rg in requested.items():
            scopes = approved.get(controller) or []
            if not scopes:
                continue  # declined by the subject
            if ceiling is not None:
                policy, allowed = ceiling[0], ceiling[1].get(controller, set())
            else:
                policy = await self.current_policy(req.partner_id, controller)
                allowed = set(policy.allowed_data_scopes or []) if policy else set()
            effective = sorted(set(scopes) & allowed)
            if not effective:
                continue
            fetch_type = fetch_type or (policy.fetch_type if policy else None)
            grants.append(
                {
                    "data_controller": controller,
                    "data_scopes": rg["data_scopes"],
                    "granted_scopes": sorted(scopes),
                    "effective_data_scopes": effective,
                    **policy_fields(policy),
                }
            )
        if not grants:
            raise LifecycleError(400, "no granted scope permitted by policy")

        now = datetime.now(timezone.utc)
        default_validity = timedelta(days=365)
        if ceiling is not None and ceiling[0].max_validity_duration:
            try:
                default_validity = min(
                    default_validity, iso_duration_to_timedelta(ceiling[0].max_validity_duration)
                )
            except ValueError:
                pass
        artefact = ConsentArtefact(
            subject_id_type=req.subject_id_type,
            subject_id_value=req.subject_id_value,
            controller_id=grants[0]["data_controller"] if len(grants) == 1 else None,
            partner_id=req.partner_id,
            purpose=req.purpose,
            data_scopes=req.requested_scopes,
            effective_data_scopes=sorted(
                {s for g in grants for s in g["effective_data_scopes"]}
            ),
            grants=grants,
            fetch_type=fetch_type or "oneshot",
            valid_from=req.valid_from or now,
            valid_until=req.valid_until or (now + default_validity),
            source=ArtefactSource.originated.value,
            **common_policy_fields(grants),
            auth_context_id=ctx.id,
            consent_request_id=req.id,
            use_case=req.use_case if ceiling is not None else None,
            status=ArtefactStatus.active.value,
        )
        receipt = self.receipts.build_receipt(artefact)
        req.status = RequestStatus.approved.value
        session.add(artefact)
        session.add(receipt)
        return artefact

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _latest_auth_context(self, session, request_id: str) -> Optional[AuthContext]:
        from sqlalchemy import select

        result = await session.execute(
            select(AuthContext)
            .where(AuthContext.consent_request_id == request_id)
            .order_by(AuthContext.created_at.desc())
        )
        return result.scalars().first()

    def _decode_id_token(self, id_token: str) -> tuple[dict, bool]:
        """Return (claims, validated). Verifies against the IdP JWKS if configured."""
        if _config.oidc_jwks_url:
            try:
                jwk_client = jwt.PyJWKClient(_config.oidc_jwks_url)
                signing_key = jwk_client.get_signing_key_from_jwt(id_token)
                claims = jwt.decode(
                    id_token,
                    signing_key.key,
                    algorithms=["RS256", "ES256", "EdDSA"],
                    audience=_config.oidc_audience or None,
                    issuer=_config.oidc_issuer or None,
                    options={"verify_aud": bool(_config.oidc_audience)},
                )
                return claims, True
            except Exception as exc:
                raise LifecycleError(401, f"ID token validation failed: {exc}")
        _logger.warning(
            "oidc_jwks_url not configured — decoding ID token WITHOUT signature "
            "verification (dev only)."
        )
        claims = jwt.decode(id_token, options={"verify_signature": False})
        return claims, False
