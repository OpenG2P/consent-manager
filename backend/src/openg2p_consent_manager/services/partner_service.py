import logging
from datetime import datetime, timezone
from typing import Optional

from openg2p_fastapi_common.service import BaseService
from sqlalchemy import func, select

from ..config import Settings
from ..db import async_session
from ..models import (
    KeyStatus,
    Partner,
    PartnerKey,
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
        async with async_session()() as session:
            partner = Partner(
                name=data.name,
                org_name=data.org_name,
                audience=data.audience,
                controller_id=data.controller_id,
                jwks_url=data.jwks_url,
                status=PartnerStatus.active.value,
            )
            session.add(partner)
            await session.commit()
            await session.refresh(partner)
            return partner

    async def get_partner(self, partner_id: str) -> Optional[Partner]:
        async with async_session()() as session:
            return await session.get(Partner, partner_id)

    async def update_partner(self, partner_id: str, data) -> Optional[Partner]:
        async with async_session()() as session:
            partner = await session.get(Partner, partner_id)
            if partner is None:
                return None
            for field in ("name", "org_name", "status", "jwks_url"):
                value = getattr(data, field, None)
                if value is not None:
                    setattr(partner, field, value)
            await session.commit()
            await session.refresh(partner)
        self._invalidate(partner.audience)
        return partner

    # ── Admin: keys ──────────────────────────────────────────────────────────

    async def add_key(self, partner_id: str, data) -> Optional[PartnerKey]:
        async with async_session()() as session:
            partner = await session.get(Partner, partner_id)
            if partner is None:
                return None
            key = PartnerKey(
                partner_id=partner_id,
                kid=data.kid,
                algorithm=data.algorithm,
                public_key=data.public_key,
                status=KeyStatus.active.value,
                not_before=data.not_before,
                not_after=data.not_after,
            )
            session.add(key)
            await session.commit()
            await session.refresh(key)
            audience = partner.audience
        self._invalidate(audience)
        return key

    async def revoke_key(self, partner_id: str, kid: str) -> bool:
        async with async_session()() as session:
            result = await session.execute(
                select(PartnerKey).where(
                    PartnerKey.partner_id == partner_id, PartnerKey.kid == kid
                )
            )
            key = result.scalars().first()
            if key is None:
                return False
            key.status = KeyStatus.revoked.value
            partner = await session.get(Partner, partner_id)
            audience = partner.audience if partner else None
            await session.commit()
        if audience:
            self._invalidate(audience)
        return True

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
        """Return the active partner, its active keys, and active policy by
        audience — cached per pod for the validation hot path.

        Shape: {"partner": Partner, "keys": {kid: PartnerKey}, "policy": PartnerPolicy}
        Returns None if the partner is unknown or suspended.
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

            keys_result = await session.execute(
                select(PartnerKey).where(
                    PartnerKey.partner_id == partner.id,
                    PartnerKey.status == KeyStatus.active.value,
                )
            )
            keys = {k.kid: k for k in keys_result.scalars().all()}

            policy_result = await session.execute(
                select(PartnerPolicy).where(
                    PartnerPolicy.partner_id == partner.id,
                    PartnerPolicy.status == PolicyStatus.active.value,
                )
            )
            policy = policy_result.scalars().first()

        material = {"partner": partner, "keys": keys, "policy": policy}
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
