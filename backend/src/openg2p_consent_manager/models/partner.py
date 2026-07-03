from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseORMModelWithId


class PartnerStatus(str, Enum):
    active = "active"
    suspended = "suspended"


class ApprovalStatus(str, Enum):
    # not_required: onboarding was immediate (AWE disabled).
    # pending: submitted to AWE, awaiting a terminal webhook.
    # approved / rejected: AWE delivered its terminal decision.
    not_required = "not_required"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class PolicyStatus(str, Enum):
    active = "active"
    superseded = "superseded"


class FetchType(str, Enum):
    oneshot = "oneshot"
    periodic = "periodic"


class Partner(BaseORMModelWithId):
    """A third party onboarded to receive data, bound by a policy."""

    __tablename__ = "partners"

    name: Mapped[str] = mapped_column(String(255))
    org_name: Mapped[str] = mapped_column(String(255))
    # The identifier this partner presents as `aud` in a consent object.
    audience: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    controller_id: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default=PartnerStatus.active.value)
    # The partner's reference in the Partner Management service — used to fetch
    # its public keys from PM's key API (GET /keys/{partner_mgmt_id}). Signing
    # keys are owned by PM, not CM. Falls back to `audience` when unset.
    partner_mgmt_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )

    # Onboarding approval (AWE). approval_status is the source of truth for the
    # onboarding gate; status stays non-active (suspended) while pending so the
    # verification hot path — which filters status==active — never releases data
    # for an unapproved partner. awe_request_id correlates to the AWE request.
    approval_status: Mapped[str] = mapped_column(
        String(20), default=ApprovalStatus.not_required.value
    )
    awe_request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )


class PartnerPolicy(BaseORMModelWithId):
    """The ceiling on everything a partner can be granted. Versioned."""

    __tablename__ = "partner_policies"
    __table_args__ = (
        UniqueConstraint("partner_id", "version", name="uq_partner_policy_version"),
    )

    partner_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=PolicyStatus.active.value)

    allowed_data_scopes: Mapped[list] = mapped_column(JSONB, default=list)
    allowed_purposes: Mapped[list] = mapped_column(JSONB, default=list)
    allowed_subject_id_types: Mapped[list] = mapped_column(JSONB, default=list)
    allowed_signing_algs: Mapped[list] = mapped_column(JSONB, default=list)

    # ISO-8601 durations, e.g. "P1Y", "P30D". Parsed during evaluation.
    max_validity_duration: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    fetch_type: Mapped[str] = mapped_column(String(20), default=FetchType.oneshot.value)
    max_fetch_frequency: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    data_life: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    effective_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
