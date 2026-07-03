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


class PolicyStatus(str, Enum):
    # A versioned data-share policy's lifecycle. When AWE approval is enabled, a
    # widening policy is created `pending` and only becomes `active` once AWE
    # approves it (superseding the prior active version); `rejected` if declined.
    pending = "pending"
    active = "active"
    superseded = "superseded"
    rejected = "rejected"


class FetchType(str, Enum):
    oneshot = "oneshot"
    periodic = "periodic"


class Partner(BaseORMModelWithId):
    """A partner *policy binding*: it binds a Partner-Management partner (by
    ``partner_mgmt_id``) to a data controller and a versioned data-share policy.

    Partner identity, org, lifecycle and signing keys are owned by the Partner
    Management service — this row is NOT the partner record, only CM's binding of
    a policy to that partner for a given controller. ``name`` is a non-authoritative
    display label only.
    """

    __tablename__ = "partners"

    # Non-authoritative display label (identity lives in Partner Management).
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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


class PartnerPolicy(BaseORMModelWithId):
    """The ceiling on everything a partner can be granted. Versioned. A widening
    version may sit in `pending` awaiting AWE approval before it goes active."""

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

    # AWE approval correlation (set when this version is submitted for approval).
    awe_request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    effective_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
