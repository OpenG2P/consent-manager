from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseORMModelWithId


class PartnerStatus(str, Enum):
    active = "active"
    suspended = "suspended"


class KeyStatus(str, Enum):
    active = "active"
    rotated = "rotated"
    revoked = "revoked"


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
    # Optional JWKS endpoint the CM may poll instead of locally stored keys.
    jwks_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)


class PartnerKey(BaseORMModelWithId):
    """A public key used to verify a partner's signed consent objects."""

    __tablename__ = "partner_keys"
    __table_args__ = (UniqueConstraint("partner_id", "kid", name="uq_partner_kid"),)

    partner_id: Mapped[str] = mapped_column(String, index=True)
    kid: Mapped[str] = mapped_column(String(255), index=True)
    algorithm: Mapped[str] = mapped_column(String(20))  # EdDSA | ES256 | RS256
    public_key: Mapped[str] = mapped_column(Text)  # PEM
    status: Mapped[str] = mapped_column(String(20), default=KeyStatus.active.value)
    not_before: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    not_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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
