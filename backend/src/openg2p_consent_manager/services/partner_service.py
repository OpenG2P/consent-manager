import logging
from datetime import datetime, timezone
from typing import Optional

from openg2p_fastapi_common.service import BaseService
from sqlalchemy import func, select

from ..config import Settings
from ..db import async_session
from ..models import (
    Partner,
    PartnerPolicy,
    PartnerStatus,
    PolicyStatus,
)
from ..utils import TTLCache, iso_duration_to_timedelta

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


class PartnerConflict(Exception):
    """A binding request conflicts with existing bindings (HTTP 409)."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def _cache_key(audience: str, controller_id: str) -> str:
    return f"{audience}\x1f{controller_id}"


class PartnerService(BaseService):
    """Partner *policy bindings* (admin) plus the cached lookups the hot path
    needs. Partner identity + keys live in Partner Management; a row here binds a
    PM partner to a controller and a versioned data-share policy. One partner
    (audience) may have several bindings — one per controller."""

    def __init__(self, name="", **kwargs):
        super().__init__(name, **kwargs)
        self._cache = TTLCache(_config.partner_cache_ttl_sec)

    # ── Admin: bindings ──────────────────────────────────────────────────────

    async def create_partner(self, data) -> Partner:
        """Create a binding of a partner (audience) to one controller.

        A binding is created active. Partner *identity* onboarding/approval is
        Partner Management's concern; CM only gates data-share POLICY widening
        (see upsert_policy). A binding with no policy simply denies everything
        until a policy is set.

        The same audience may be bound to several controllers (one binding and
        policy per controller). All bindings of one audience share its PM
        reference: a new binding inherits ``partner_mgmt_id`` from the existing
        ones when omitted, and may not name a different one. Raises
        PartnerConflict on a duplicate (audience, controller) or a PM-reference
        mismatch.
        """
        async with async_session()() as session:
            result = await session.execute(
                select(Partner).where(Partner.audience == data.audience)
            )
            siblings = list(result.scalars().all())
            if any(p.controller_id == data.controller_id for p in siblings):
                raise PartnerConflict(
                    f"audience '{data.audience}' is already bound to controller "
                    f"'{data.controller_id}'"
                )
            partner_mgmt_id = data.partner_mgmt_id
            if siblings:
                existing_ref = siblings[0].partner_mgmt_id
                if partner_mgmt_id is None:
                    partner_mgmt_id = existing_ref
                elif (partner_mgmt_id or data.audience) != (existing_ref or data.audience):
                    raise PartnerConflict(
                        f"audience '{data.audience}' is bound with partner_mgmt_id "
                        f"'{existing_ref or data.audience}'; a new binding cannot use "
                        f"'{partner_mgmt_id}'"
                    )
            partner = Partner(
                name=data.name if data.name is not None else (
                    siblings[0].name if siblings else None
                ),
                audience=data.audience,
                controller_id=data.controller_id,
                partner_mgmt_id=partner_mgmt_id,
                status=PartnerStatus.active.value,
            )
            session.add(partner)
            await session.commit()
            await session.refresh(partner)
            return partner

    async def get_partner(self, partner_id: str) -> Optional[Partner]:
        async with async_session()() as session:
            return await session.get(Partner, partner_id)

    async def list_partners(
        self,
        controller_id: Optional[str] = None,
        status: Optional[str] = None,
        audience: Optional[str] = None,
    ) -> list:
        """List bindings for the admin console, newest first. Optional filters by
        controller (registry), lifecycle status and audience (all bindings of
        one partner)."""
        async with async_session()() as session:
            query = select(Partner)
            if audience:
                query = query.where(Partner.audience == audience)
            if controller_id:
                query = query.where(Partner.controller_id == controller_id)
            if status:
                query = query.where(Partner.status == status)
            query = query.order_by(Partner.created_at.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def update_partner(self, partner_id: str, data) -> Optional[Partner]:
        """Update one binding's label/status. A ``partner_mgmt_id`` change is
        partner identity, so it is applied to every binding of the audience."""
        async with async_session()() as session:
            partner = await session.get(Partner, partner_id)
            if partner is None:
                return None
            for field in ("name", "status"):
                value = getattr(data, field, None)
                if value is not None:
                    setattr(partner, field, value)
            touched = [partner]
            if getattr(data, "partner_mgmt_id", None) is not None:
                result = await session.execute(
                    select(Partner).where(Partner.audience == partner.audience)
                )
                touched = list(result.scalars().all())
                for binding in touched:
                    binding.partner_mgmt_id = data.partner_mgmt_id
            await session.commit()
            await session.refresh(partner)
        for binding in touched:
            self._invalidate(binding.audience, binding.controller_id)
        return partner

    # ── Admin: policy (versioned) ────────────────────────────────────────────

    async def upsert_policy(self, partner_id: str, data) -> Optional[PartnerPolicy]:
        """Create a new data-share policy version.

        If AWE approval is enabled AND the change *widens* access relative to the
        current active policy (or is the first policy), the new version is created
        ``pending`` and does NOT supersede the active one — the caller submits it
        to AWE and it only goes active on approval. A non-widening change (or AWE
        disabled) activates immediately, superseding the prior active version.
        """
        async with async_session()() as session:
            partner = await session.get(Partner, partner_id)
            if partner is None:
                return None

            result = await session.execute(
                select(PartnerPolicy)
                .where(PartnerPolicy.partner_id == partner_id)
                .order_by(PartnerPolicy.version.desc())
            )
            existing = list(result.scalars().all())
            active = next(
                (p for p in existing if p.status == PolicyStatus.active.value), None
            )
            next_version = (existing[0].version + 1) if existing else 1

            gated = _config.awe_enabled and self._is_widening(data, active)

            if gated:
                status = PolicyStatus.pending.value
                effective_from = None
                # Do NOT supersede the active policy — it stays in force until
                # this pending version is approved.
            else:
                status = PolicyStatus.active.value
                effective_from = datetime.now(timezone.utc)
                if active is not None:
                    active.status = PolicyStatus.superseded.value

            policy = PartnerPolicy(
                partner_id=partner_id,
                version=next_version,
                status=status,
                allowed_data_scopes=data.allowed_data_scopes,
                allowed_purposes=data.allowed_purposes,
                allowed_subject_id_types=data.allowed_subject_id_types,
                allowed_signing_algs=data.allowed_signing_algs,
                max_validity_duration=data.max_validity_duration,
                fetch_type=data.fetch_type,
                max_fetch_frequency=data.max_fetch_frequency,
                data_life=data.data_life,
                effective_from=effective_from,
            )
            session.add(policy)
            await session.commit()
            await session.refresh(policy)
            audience, controller_id = partner.audience, partner.controller_id

        if not gated:
            self._invalidate(audience, controller_id)  # active policy changed
        return policy

    async def set_policy_awe_request_id(self, policy_id: str, awe_request_id: str) -> None:
        async with async_session()() as session:
            policy = await session.get(PartnerPolicy, policy_id)
            if policy is not None:
                policy.awe_request_id = awe_request_id
                await session.commit()

    async def apply_policy_decision(
        self, awe_request_id: str, artifact_id: str, approved: bool
    ) -> bool:
        """Apply a terminal AWE decision to a pending policy version. On approve,
        activate it and supersede the prior active version for that partner; on
        reject, mark it rejected. Matches by AWE request id, else artifact id
        (== policy id). Returns False if no pending policy correlates."""
        async with async_session()() as session:
            policy = None
            if awe_request_id:
                res = await session.execute(
                    select(PartnerPolicy).where(
                        PartnerPolicy.awe_request_id == awe_request_id
                    )
                )
                policy = res.scalars().first()
            if policy is None and artifact_id:
                policy = await session.get(PartnerPolicy, artifact_id)
            if policy is None:
                return False
            # Idempotent: a re-delivered webhook for an already-decided version.
            if policy.status != PolicyStatus.pending.value:
                partner = await session.get(Partner, policy.partner_id)
                if partner:
                    self._invalidate(partner.audience, partner.controller_id)
                return True

            if approved:
                # Supersede whatever is currently active for this partner.
                res = await session.execute(
                    select(PartnerPolicy).where(
                        PartnerPolicy.partner_id == policy.partner_id,
                        PartnerPolicy.status == PolicyStatus.active.value,
                    )
                )
                for old in res.scalars().all():
                    old.status = PolicyStatus.superseded.value
                policy.status = PolicyStatus.active.value
                policy.effective_from = datetime.now(timezone.utc)
            else:
                policy.status = PolicyStatus.rejected.value

            partner = await session.get(Partner, policy.partner_id)
            key = (partner.audience, partner.controller_id) if partner else None
            await session.commit()
        if key:
            self._invalidate(*key)
        return True

    async def list_policies(self, partner_id: str) -> Optional[list]:
        """All policy versions for a binding, newest first. None if no binding."""
        async with async_session()() as session:
            partner = await session.get(Partner, partner_id)
            if partner is None:
                return None
            result = await session.execute(
                select(PartnerPolicy)
                .where(PartnerPolicy.partner_id == partner_id)
                .order_by(PartnerPolicy.version.desc())
            )
            return list(result.scalars().all())

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

    # ── Widening detection (drives whether AWE approval is required) ──────────

    @staticmethod
    def _is_widening(data, active: Optional[PartnerPolicy]) -> bool:
        """True if `data` grants anything the current active policy did not — a
        larger allowed set, or a longer validity/data-life. The first policy
        (no active prior) counts as a widening (a grant from nothing)."""
        if active is None:
            return True
        for field in (
            "allowed_data_scopes",
            "allowed_purposes",
            "allowed_subject_id_types",
            "allowed_signing_algs",
        ):
            new_set = set(getattr(data, field, None) or [])
            old_set = set(getattr(active, field, None) or [])
            if new_set - old_set:
                return True
        if PartnerService._duration_loosened(
            data.max_validity_duration, active.max_validity_duration
        ):
            return True
        if PartnerService._duration_loosened(data.data_life, active.data_life):
            return True
        return False

    @staticmethod
    def _duration_loosened(new: Optional[str], old: Optional[str]) -> bool:
        """True if ISO-8601 duration `new` permits a LONGER window than `old`.
        None means "no cap" (widest). On a parse error, err toward requiring
        approval (return True)."""
        if new == old:
            return False
        if new is None:  # removed the cap → wider
            return old is not None
        if old is None:  # added a cap → narrower
            return False
        try:
            return iso_duration_to_timedelta(new) > iso_duration_to_timedelta(old)
        except Exception:
            return True

    # ── Hot path: cached verification material ───────────────────────────────

    async def get_verification_material(
        self, audience: str, controller_id: str
    ) -> Optional[dict]:
        """Return the active binding of ``audience`` to ``controller_id`` and its
        active policy — cached per pod for the validation hot path. The policy is
        per (audience, controller): a partner bound to two controllers has two
        independent policies.

        Partner public keys are NOT included here: they are owned by the Partner
        Management service and fetched separately (and cached with their own
        discipline) by the shared fastapi-common CryptoHelper (partner-mgmt
        backend) during consent-JWS verification, keyed by the partner's
        ``partner_mgmt_id``. This method only resolves the onboarded party +
        policy. Returns None if the partner has no active binding to the
        controller (unknown, suspended, or not bound to that controller).

        Shape: {"partner": Partner, "policy": PartnerPolicy | None}
        """
        key = _cache_key(audience, controller_id)
        if _config.partner_cache_enabled:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        async with async_session()() as session:
            result = await session.execute(
                select(Partner).where(
                    Partner.audience == audience,
                    Partner.controller_id == controller_id,
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
            self._cache.set(key, material)
        return material

    async def get_binding(self, audience: str, controller_id: str) -> Optional[Partner]:
        """The binding of ``audience`` to ``controller_id`` (any status)."""
        async with async_session()() as session:
            result = await session.execute(
                select(Partner).where(
                    Partner.audience == audience, Partner.controller_id == controller_id
                )
            )
            return result.scalars().first()

    def _invalidate(self, audience: Optional[str], controller_id: Optional[str]) -> None:
        if audience and controller_id:
            self._cache.invalidate(_cache_key(audience, controller_id))

    async def count_partners(self) -> int:
        async with async_session()() as session:
            result = await session.execute(select(func.count(Partner.id)))
            return int(result.scalar() or 0)
