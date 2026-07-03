import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from openg2p_fastapi_common.service import BaseService
from sqlalchemy import select

from ..config import Settings
from ..db import async_session
from ..models import (
    ArtefactSource,
    ArtefactStatus,
    ConsentArtefact,
    DecisionLog,
)
from ..schemas.common import ReasonCode
from ..schemas.verification import Decision, ValidateRequest
from ..utils.canonical import canonical_bytes, sha256_hex
from .crypto_service import CryptoService
from .partner_key_store import PartnerMgmtKeyStore
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
        self.keys = PartnerMgmtKeyStore.get_component()
        self.crypto = CryptoService.get_component()
        self.policy = PolicyService.get_component()
        self.receipts = ReceiptService.get_component()

    async def validate(self, parsed: ValidateRequest, raw_consent_object: dict) -> Decision:
        now = datetime.now(timezone.utc)
        obj = parsed.consent_object
        ctx_hash = sha256_hex(canonical_bytes(raw_consent_object))

        # Idempotency: the same object (jti) returns its existing decision.
        existing = await self._existing_artefact(obj.jti)
        if existing is not None:
            return self._decision_from_artefact(existing, now)

        # 2. Known party — partner + keys + policy (cached).
        material = await self.partners.get_verification_material(obj.aud)
        if material is None:
            return await self._deny(
                ReasonCode.unknown_partner, "partner not onboarded or suspended",
                now, ctx_hash, jti=obj.jti,
            )
        partner = material["partner"]
        policy = material["policy"]
        policy_version = policy.version if policy else None

        # 3. Signature — resolve the verifying key from Partner Management by the
        # partner's PM reference (partner_mgmt_id, falling back to audience) and
        # the object's kid, then check the algorithm is allowed and verify.
        reference_id = partner.partner_mgmt_id or partner.audience
        key = await self.keys.get_key(reference_id, obj.signature.kid)
        if key is None:
            return await self._deny(
                ReasonCode.unknown_partner,
                f"no verifying key for kid '{obj.signature.kid}' from partner management",
                now, ctx_hash, partner_id=partner.id, jti=obj.jti,
                policy_version=policy_version,
            )
        # Guard against algorithm confusion: the declared alg must match the key
        # PM registered for this kid.
        if key.get("algorithm") and obj.signature.algorithm != key["algorithm"]:
            return await self._deny(
                ReasonCode.signature_invalid, "signing algorithm does not match key",
                now, ctx_hash, partner_id=partner.id, jti=obj.jti,
                policy_version=policy_version,
            )
        if policy and policy.allowed_signing_algs and (
            obj.signature.algorithm not in policy.allowed_signing_algs
        ):
            return await self._deny(
                ReasonCode.signature_invalid, "signing algorithm not permitted",
                now, ctx_hash, partner_id=partner.id, jti=obj.jti,
                policy_version=policy_version,
            )
        signing_input = canonical_bytes(
            {k: v for k, v in raw_consent_object.items() if k != "signature"}
        )
        if not self.crypto.verify(
            key["public_key"], obj.signature.algorithm, signing_input, obj.signature.value
        ):
            return await self._deny(
                ReasonCode.signature_invalid, "signature did not verify",
                now, ctx_hash, partner_id=partner.id, jti=obj.jti,
                policy_version=policy_version,
            )

        # 10. Replay / freshness — issued_at within the configured window.
        issued_at = _aware(obj.issued_at)
        skew = timedelta(seconds=_config.replay_freshness_window_sec)
        if abs((now - issued_at).total_seconds()) > skew.total_seconds():
            return await self._deny(
                ReasonCode.replay, "issued_at outside freshness window",
                now, ctx_hash, partner_id=partner.id, jti=obj.jti,
                policy_version=policy_version,
            )

        # 4–8. Policy evaluation (audience, subject, purpose, scope, validity).
        result = self.policy.evaluate(obj, material, parsed.request_context)
        if not result.permit:
            return await self._deny(
                result.reason, result.detail, now, ctx_hash,
                partner_id=partner.id, jti=obj.jti, policy_version=result.policy_version,
            )

        # Permit — mint canonical artefact + signed receipt + decision log.
        return await self._permit(
            obj, partner, result, now, ctx_hash
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    async def _existing_artefact(self, jti: str) -> Optional[ConsentArtefact]:
        async with async_session()() as session:
            result = await session.execute(
                select(ConsentArtefact).where(ConsentArtefact.object_jti == jti)
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
                detail="consent revoked", evaluated_at=now,
            )
        if status == ArtefactStatus.expired.value:
            return Decision(
                decision="deny", reason_code=ReasonCode.expired,
                detail="consent expired", evaluated_at=now,
            )
        return Decision(
            decision="permit", reason_code=ReasonCode.ok,
            consent_id=artefact.id,
            subject_id=SubjectId(type=artefact.subject_id_type, value=artefact.subject_id_value),
            effective_data_scopes=artefact.effective_data_scopes,
            valid_until=artefact.valid_until, policy_version=artefact.policy_version,
            evaluated_at=now,
        )

    async def _permit(self, obj, partner, result, now, ctx_hash) -> Decision:
        from ..schemas.common import SubjectId

        artefact = ConsentArtefact(
            subject_id_type=obj.subject_id.type,
            subject_id_value=obj.subject_id.value,
            controller_id=partner.controller_id,
            partner_id=partner.id,
            purpose=obj.purpose,
            data_scopes=obj.data_scopes,
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
                    decision="permit", reason_code=ReasonCode.ok.value,
                    policy_version=result.policy_version, request_ctx_hash=ctx_hash,
                )
            )
            await session.commit()
            await session.refresh(artefact)
            await session.refresh(receipt)

        return Decision(
            decision="permit", reason_code=ReasonCode.ok,
            consent_id=artefact.id, receipt_id=receipt.id,
            subject_id=SubjectId(type=obj.subject_id.type, value=obj.subject_id.value),
            effective_data_scopes=result.effective_scopes,
            valid_until=artefact.valid_until, policy_version=result.policy_version,
            evaluated_at=now,
        )

    async def _deny(
        self, reason: ReasonCode, detail: Optional[str], now, ctx_hash,
        partner_id: Optional[str] = None, jti: Optional[str] = None,
        policy_version: Optional[int] = None,
    ) -> Decision:
        async with async_session()() as session:
            session.add(
                DecisionLog(
                    partner_id=partner_id, object_jti=jti, decision="deny",
                    reason_code=reason.value, detail=detail,
                    policy_version=policy_version, request_ctx_hash=ctx_hash,
                )
            )
            await session.commit()
        return Decision(
            decision="deny", reason_code=reason, detail=detail, evaluated_at=now,
        )
