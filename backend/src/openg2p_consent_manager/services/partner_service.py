import logging
from datetime import datetime, timezone
from typing import Optional

from openg2p_fastapi_common.service import BaseService
from sqlalchemy import func, select

from ..config import Settings
from ..db import async_session
from ..models import (
    ApprovalStatus,
    Partner,
    PartnerPolicy,
    PartnerStatus,
    PolicyStatus,
)
from ..utils import TTLCache

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


class PartnerService(BaseService):
    """Partner onboarding (admin) plus the cached lookups the hot path needs."""

    def __init__(self, name="", **kwargs):
        super().__init__(name, **kwargs)
        self._cache = TTLCache(_config.partner_cache_ttl_sec)

    # ── Admin: partners ──────────────────────────────────────────────────────

    async def create_partner(self, data) -> Partner:
        # When AWE onboarding approval is enabled, the partner is born suspended
        # + pending — it must NOT validate consents until AWE approves. The
        # verification hot path filters status==active, so keeping status
        # suspended is what actually enforces the gate; approval_status carries
        # the human-facing state. When AWE is disabled, onboarding is immediate.
        gated = _config.awe_enabled
        async with async_session()() as session:
            partner = Partner(
                name=data.name,
                org_name=data.org_name,
                audience=data.audience,
                controller_id=data.controller_id,
                partner_mgmt_id=data.partner_mgmt_id,
                status=(
                    PartnerStatus.suspended.value if gated else PartnerStatus.active.value
                ),
                approval_status=(
                    ApprovalStatus.pending.value
                    if gated
                    else ApprovalStatus.not_required.value
                ),
            )
            session.add(partner)
            await session.commit()
            await session.refresh(partner)
            return partner

    async def set_awe_request_id(self, partner_id: str, awe_request_id: str) -> None:
        """Record the AWE request correlating to a partner's onboarding."""
        async with async_session()() as session:
            partner = await session.get(Partner, partner_id)
            if partner is not None:
                partner.awe_request_id = awe_request_id
                await session.commit()

    async def apply_onboarding_decision(
        self, awe_request_id: str, artifact_id: str, approved: bool
    ) -> bool:
        """Flip a partner's onboarding gate from a terminal AWE webhook. Matches
        the partner by AWE request id (preferred) or the artifact id (== partner
        id) as a fallback. Returns False if no partner correlates."""
        async with async_session()() as session:
            partner = None
            if awe_request_id:
                result = await session.execute(
                    select(Partner).where(Partner.awe_request_id == awe_request_id)
                )
                partner = result.scalars().first()
            if partner is None and artifact_id:
                partner = await session.get(Partner, artifact_id)
            if partner is None:
                return False

            if approved:
                partner.status = PartnerStatus.active.value
                partner.approval_status = ApprovalStatus.approved.value
            else:
                partner.status = PartnerStatus.suspended.value
                partner.approval_status = ApprovalStatus.rejected.value
            audience = partner.audience
            await session.commit()
        self._invalidate(audience)
        return True

    async def get_partner(self, partner_id: str) -> Optional[Partner]:
        async with async_session()() as session:
            return await session.get(Partner, partner_id)

    async def list_partners(
        self, controller_id: Optional[str] = None, status: Optional[str] = None
    ) -> list:
        """List partners for the admin console, newest first. Optional filters by
        controller (registry) and lifecycle status."""
        async with async_session()() as session:
            query = select(Partner)
            if controller_id:
                query = query.where(Partner.controller_id == controller_id)
            if status:
                query = query.where(Partner.status == status)
            query = query.order_by(Partner.created_at.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_partner(self, partner_id: str, data) -> Optional[Partner]:
        async with async_session()() as session:
            partner = await session.get(Partner, partner_id)
            if partner is None:
                return None
            for field in ("name", "org_name", "status", "partner_mgmt_id"):
                value = getattr(data, field, None)
                if value is not None:
                    setattr(partner, field, value)
            await session.commit()
            await session.refresh(partner)
        self._invalidate(partner.audience)
        return partner

    # ── Admin: policy (versioned) ────────────────────────────────────────────

    async def upsert_policy(self, partner_id: str, data) -> Optional[PartnerPolicy]:
        async with async_session()() as session:
            partner = await session.get(Partner, partner_id)
            if partner is None:
                return None
            # Supersede the current active policy and bump the version.
            result = await session.execute(
                select(PartnerPolicy)
                .where(PartnerPolicy.partner_id == partner_id)
                .order_by(PartnerPolicy.version.desc())
            )
            existing = result.scalars().all()
            next_version = (existing[0].version + 1) if existing else 1
            for old in existing:
                if old.status == PolicyStatus.active.value:
                    old.status = PolicyStatus.superseded.value

            policy = PartnerPolicy(
                partner_id=partner_id,
                version=next_version,
                status=PolicyStatus.active.value,
                allowed_data_scopes=data.allowed_data_scopes,
                allowed_purposes=data.allowed_purposes,
                allowed_subject_id_types=data.allowed_subject_id_types,
                allowed_signing_algs=data.allowed_signing_algs,
                max_validity_duration=data.max_validity_duration,
                fetch_type=data.fetch_type,
                max_fetch_frequency=data.max_fetch_frequency,
                data_life=data.data_life,
                effective_from=datetime.now(timezone.utc),
            )
            session.add(policy)
            await session.commit()
            await session.refresh(policy)
            audience = partner.audience
        self._invalidate(audience)
        return policy

    async def get_policy(
        self, partner_id: str, version: Optional[int] = None
    ) -> Optional[PartnerPolicy]:
        async with async_session()() as session:
            query = select(PartnerPolicy).where(PartnerPolicy.partner_id == partner_id)
            if version is not None:
                query = query.where(PartnerPolicy.version == version)
            else:
                query = query.where(
                    PartnerPolicy.status == PolicyStatus.active.value
                )
            result = await session.execute(query)
            return result.scalars().first()

    # ── Hot path: cached verification material ───────────────────────────────

    async def get_verification_material(self, audience: str) -> Optional[dict]:
        """Return the active partner and its active policy by audience — cached
        per pod for the validation hot path.

        Partner public keys are NOT included here: they are owned by the Partner
        Management service and fetched separately (and cached with their own
        discipline) via PartnerMgmtKeyStore, keyed by the partner's
        ``partner_mgmt_id``. This method only resolves the onboarded party +
        policy. Returns None if the partner is unknown or suspended.

        Shape: {"partner": Partner, "policy": PartnerPolicy | None}
        """
        if _config.partner_cache_enabled:
            cached = self._cache.get(audience)
            if cached is not None:
                return cached

        async with async_session()() as session:
            result = await session.execute(
                select(Partner).where(
                    Partner.audience == audience,
                    Partner.status == PartnerStatus.active.value,
                )
            )
            partner = result.scalars().first()
            if partner is None:
                return None

            policy_result = await session.execute(
                select(PartnerPolicy).where(
                    PartnerPolicy.partner_id == partner.id,
                    PartnerPolicy.status == PolicyStatus.active.value,
                )
            )
            policy = policy_result.scalars().first()

        material = {"partner": partner, "policy": policy}
        if _config.partner_cache_enabled:
            self._cache.set(audience, material)
        return material

    def _invalidate(self, audience: Optional[str]) -> None:
        if audience:
            self._cache.invalidate(audience)

    async def count_partners(self) -> int:
        async with async_session()() as session:
            result = await session.execute(select(func.count(Partner.id)))
            return int(result.scalar() or 0)
