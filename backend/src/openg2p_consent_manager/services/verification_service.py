import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from openg2p_fastapi_common.service import BaseService
from openg2p_fastapi_common.utils.crypto import build_crypto_helper
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..config import Settings
from ..db import async_session
from ..models import (
    ArtefactSource,
    ArtefactStatus,
    ConsentArtefact,
    DecisionLog,
)
from ..schemas.common import ReasonCode
from ..schemas.verification import ConsentObject, Decision, ValidateRequest
from ..utils.canonical import b64url_decode, sha256_hex
from .partner_service import PartnerService
from .policy_service import PolicyService
from .receipt_service import ReceiptService

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class VerificationService(BaseService):
    """The PDP hot path: verify an embedded consent object → decision."""

    def __init__(self, name="", **kwargs):
        super().__init__(name, **kwargs)
        self.partners = PartnerService.get_component()
        # Partner consent-JWS verification via the shared fastapi-common crypto
        # helper (partner-mgmt backend fetches keys from Partner Management).
        self.crypto_helper = build_crypto_helper(backend=_config.crypto_backend)
        self.policy = PolicyService.get_component()
        self.receipts = ReceiptService.get_component()

    @staticmethod
    def _decode_jws(jws: str) -> tuple[dict, dict]:
        """Return ``(claims, protected_header)`` from a compact JWS WITHOUT
        verifying — used to identify the partner and read alg/kid before the
        signature is checked. A permit is never issued on unverified claims."""
        parts = jws.split(".")
        if len(parts) != 3:
            raise ValueError("consent_jws is not a compact JWS (expected header.payload.signature)")
        protected_header = json.loads(b64url_decode(parts[0]))
        claims = json.loads(b64url_decode(parts[1]))
        return claims, protected_header

    async def validate(self, parsed: ValidateRequest) -> Decision:
        now = datetime.now(timezone.utc)
        jws = parsed.consent_jws
        # The JWS string is itself canonical/immutable, so hash it directly.
        ctx_hash = sha256_hex(jws.encode("utf-8"))

        # Recover the claims from the JWS payload (unverified) so we can identify
        # the partner and evaluate policy. The signature is verified below,
        # before any permit is issued.
        try:
            claims, jws_header = self._decode_jws(jws)
            obj = ConsentObject(**claims)
        except Exception as exc:
            _logger.info("Malformed consent JWS: %s", exc)
            return await self._deny(
                ReasonCode.malformed_object, "consent JWS could not be decoded",
                now, ctx_hash,
            )

        # 1. Grant selection — which registry (data controller) is asking.
        #    A consent with `grants` needs the caller to name its controller and
        #    is evaluated only on that controller's grant. A legacy consent is a
        #    single grant; if the caller names a controller it must match.
        if obj.has_grants:
            if not parsed.data_controller:
                return await self._deny(
                    ReasonCode.malformed_object,
                    "data_controller is required when the consent carries grants",
                    now, ctx_hash, jti=obj.jti,
                )
            controller = parsed.data_controller
            grant = obj.grant_for(controller)
            if grant is None:
                return await self._deny(
                    ReasonCode.controller_not_granted,
                    f"consent has no grant for data_controller '{controller}'",
                    now, ctx_hash, jti=obj.jti, data_controller=controller,
                )
        else:
            controller = obj.data_controller
            if parsed.data_controller and parsed.data_controller != controller:
                return await self._deny(
                    ReasonCode.controller_not_granted,
                    f"consent is for data_controller '{controller}', "
                    f"not '{parsed.data_controller}'",
                    now, ctx_hash, jti=obj.jti, data_controller=parsed.data_controller,
                )
            grant = obj.grant_for(controller)

        # 1b. Subject — a caller-declared subject of the same id type as the
        #     consent's subject must be the same subject. (A different id type is
        #     for the registry to resolve; CM cannot compare across types.)
        ctx_subject = parsed.request_context.subject_id if parsed.request_context else None
        if self._subject_mismatch(ctx_subject, obj.subject_id.type, obj.subject_id.value):
            return await self._deny(
                ReasonCode.subject_mismatch,
                "request_context.subject_id does not match the consent subject",
                now, ctx_hash, jti=obj.jti, data_controller=controller,
            )

        # 2. Known party — the partner's binding to this controller + the
        #    binding's policy (cached). Policies are per (audience, controller).
        material = await self.partners.get_verification_material(obj.aud, controller)
        if material is None:
            return await self._deny(
                ReasonCode.unknown_partner,
                f"partner not onboarded for data_controller '{controller}', or suspended",
                now, ctx_hash, jti=obj.jti, data_controller=controller,
            )
        partner = material["partner"]
        policy = material["policy"]
        policy_version = policy.version if policy else None

        # 3. Signature — verify the consent JWS against the partner's key from
        # Partner Management. The shared helper reads the kid from the JWS header,
        # fetches the key for the partner's PM reference (partner_mgmt_id, falling
        # back to audience), enforces algorithm safety, and verifies.
        reference_id = partner.partner_mgmt_id or partner.audience
        alg = jws_header.get("alg")
        if policy and policy.allowed_signing_algs and alg not in policy.allowed_signing_algs:
            return await self._deny(
                ReasonCode.signature_invalid, "signing algorithm not permitted",
                now, ctx_hash, partner_id=partner.id, jti=obj.jti, data_controller=controller,
                policy_version=policy_version,
            )
        try:
            verified = await self.crypto_helper.verify_jwt(jws, km_ref_id=reference_id)
        except Exception as exc:
            _logger.warning("Consent JWS verification error: %s", exc)
            verified = False
        if not verified:
            return await self._deny(
                ReasonCode.signature_invalid,
                "signature did not verify (or no verifying key from partner management)",
                now, ctx_hash, partner_id=partner.id, jti=obj.jti, data_controller=controller,
                policy_version=policy_version,
            )

        # Idempotency: the same object (jti) presented again for the same
        # controller returns its existing decision. Keyed per (jti, controller),
        # so one consent validated by two registries gets two decisions and
        # receipts. Checked only AFTER the binding and the signature: a stored
        # decision is never handed to an unsigned or altered object reusing a
        # known jti. The stored consent must also be this one — same partner
        # binding, subject and scopes — or the jti is being reused.
        existing = await self._existing_artefact(obj.jti, controller)
        if existing is not None:
            if (
                existing.partner_id != partner.id
                or existing.subject_id_type != obj.subject_id.type
                or existing.subject_id_value != obj.subject_id.value
                or sorted(existing.data_scopes or []) != sorted(grant.data_scopes or [])
            ):
                return await self._deny(
                    ReasonCode.replay, "jti already used for a different consent",
                    now, ctx_hash, partner_id=partner.id, jti=obj.jti, data_controller=controller,
                    policy_version=policy_version,
                )
            if self._subject_mismatch(
                ctx_subject, existing.subject_id_type, existing.subject_id_value
            ):
                return await self._deny(
                    ReasonCode.subject_mismatch,
                    "request_context.subject_id does not match the consent subject",
                    now, ctx_hash, jti=obj.jti, data_controller=controller,
                )
            return self._decision_from_artefact(existing, now)

        # 10. Replay / freshness — issued_at within the configured window.
        issued_at = _aware(obj.issued_at)
        skew = timedelta(seconds=_config.replay_freshness_window_sec)
        if abs((now - issued_at).total_seconds()) > skew.total_seconds():
            return await self._deny(
                ReasonCode.replay, "issued_at outside freshness window",
                now, ctx_hash, partner_id=partner.id, jti=obj.jti, data_controller=controller,
                policy_version=policy_version,
            )

        # 4–8. Policy evaluation (audience, subject, purpose, scope, validity).
        result = self.policy.evaluate(obj, material, parsed.request_context, grant=grant)
        if not result.permit:
            return await self._deny(
                result.reason, result.detail, now, ctx_hash,
                partner_id=partner.id, jti=obj.jti, policy_version=result.policy_version,
                data_controller=controller,
            )

        # Permit — mint canonical artefact + signed receipt + decision log for
        # this (consent, controller).
        return await self._permit(
            obj, grant, partner, result, now, ctx_hash
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    async def list_decisions(
        self,
        partner_id: Optional[str] = None,
        decision: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        """Recent validation decisions (append-only log), newest first — for the
        admin console's operational/audit status view."""
        async with async_session()() as session:
            query = select(DecisionLog)
            if partner_id:
                query = query.where(DecisionLog.partner_id == partner_id)
            if decision:
                query = query.where(DecisionLog.decision == decision)
            query = query.order_by(DecisionLog.created_at.desc()).limit(min(limit, 200))
            result = await session.execute(query)
            return list(result.scalars().all())

    @staticmethod
    def _subject_mismatch(ctx_subject, subject_type: str, subject_value: str) -> bool:
        return (
            ctx_subject is not None
            and ctx_subject.type == subject_type
            and ctx_subject.value != subject_value
        )

    async def _existing_artefact(
        self, jti: str, controller_id: str
    ) -> Optional[ConsentArtefact]:
        async with async_session()() as session:
            result = await session.execute(
                select(ConsentArtefact).where(
                    ConsentArtefact.object_jti == jti,
                    ConsentArtefact.controller_id == controller_id,
                )
            )
            return result.scalars().first()

    def _decision_from_artefact(self, artefact: ConsentArtefact, now: datetime) -> Decision:
        from ..schemas.common import SubjectId

        status = artefact.status
        if status == ArtefactStatus.active.value and _aware(artefact.valid_until) < now:
            status = ArtefactStatus.expired.value
        if status == ArtefactStatus.revoked.value:
            return Decision(
                decision="deny", reason_code=ReasonCode.revoked,
                detail="consent revoked", data_controller=artefact.controller_id,
                evaluated_at=now,
            )
        if status == ArtefactStatus.expired.value:
            return Decision(
                decision="deny", reason_code=ReasonCode.expired,
                detail="consent expired", data_controller=artefact.controller_id,
                evaluated_at=now,
            )
        return Decision(
            decision="permit", reason_code=ReasonCode.ok,
            consent_id=artefact.id,
            subject_id=SubjectId(type=artefact.subject_id_type, value=artefact.subject_id_value),
            data_controller=artefact.controller_id,
            effective_data_scopes=artefact.effective_data_scopes,
            valid_until=artefact.valid_until, policy_version=artefact.policy_version,
            evaluated_at=now,
        )

    async def _permit(self, obj, grant, partner, result, now, ctx_hash) -> Decision:
        from ..schemas.common import SubjectId

        artefact = ConsentArtefact(
            subject_id_type=obj.subject_id.type,
            subject_id_value=obj.subject_id.value,
            controller_id=grant.data_controller,
            partner_id=partner.id,
            purpose=obj.purpose,
            data_scopes=grant.data_scopes,
            effective_data_scopes=result.effective_scopes,
            fetch_type=obj.fetch_type,
            valid_from=_aware(obj.validity.valid_from),
            valid_until=_aware(obj.validity.valid_until),
            source=ArtefactSource.embedded.value,
            policy_version=result.policy_version,
            object_jti=obj.jti,
            status=ArtefactStatus.active.value,
        )
        receipt = self.receipts.build_receipt(artefact, partner)

        async with async_session()() as session:
            session.add(artefact)
            session.add(receipt)
            session.add(
                DecisionLog(
                    partner_id=partner.id, consent_id=artefact.id, object_jti=obj.jti,
                    data_controller=grant.data_controller,
                    decision="permit", reason_code=ReasonCode.ok.value,
                    policy_version=result.policy_version, request_ctx_hash=ctx_hash,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                # A concurrent validation of the same (jti, controller) won the
                # race — return its decision rather than minting a duplicate.
                await session.rollback()
                existing = await self._existing_artefact(obj.jti, grant.data_controller)
                if existing is None:
                    raise
                return self._decision_from_artefact(existing, now)
            await session.refresh(artefact)
            await session.refresh(receipt)

        return Decision(
            decision="permit", reason_code=ReasonCode.ok,
            consent_id=artefact.id, receipt_id=receipt.id,
            subject_id=SubjectId(type=obj.subject_id.type, value=obj.subject_id.value),
            data_controller=grant.data_controller,
            effective_data_scopes=result.effective_scopes,
            valid_until=artefact.valid_until, policy_version=result.policy_version,
            evaluated_at=now,
        )

    async def _deny(
        self, reason: ReasonCode, detail: Optional[str], now, ctx_hash,
        partner_id: Optional[str] = None, jti: Optional[str] = None,
        policy_version: Optional[int] = None, data_controller: Optional[str] = None,
    ) -> Decision:
        async with async_session()() as session:
            session.add(
                DecisionLog(
                    partner_id=partner_id, object_jti=jti, data_controller=data_controller,
                    decision="deny",
                    reason_code=reason.value, detail=detail,
                    policy_version=policy_version, request_ctx_hash=ctx_hash,
                )
            )
            await session.commit()
        return Decision(
            decision="deny", reason_code=reason, detail=detail,
            data_controller=data_controller, evaluated_at=now,
        )
