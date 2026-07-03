from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# A "partner" here is CM's policy *binding* (PM owns the partner identity/keys).
class PartnerCreate(BaseModel):
    # Reference to the Partner-Management partner whose keys verify this partner's
    # consent objects. When omitted, CM falls back to `audience` as the PM ref.
    partner_mgmt_id: Optional[str] = Field(None, max_length=255)
    audience: str = Field(..., min_length=1, max_length=255)
    controller_id: str = Field(..., min_length=1, max_length=255)
    # Optional display label (identity is authoritative in Partner Management).
    name: Optional[str] = Field(None, max_length=255)


class PartnerUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None  # active | suspended
    partner_mgmt_id: Optional[str] = None


class PartnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: Optional[str] = None
    audience: str
    controller_id: str
    status: str
    partner_mgmt_id: Optional[str] = None
    created_at: datetime


class PolicyUpsert(BaseModel):
    allowed_data_scopes: List[str] = Field(default_factory=list)
    allowed_purposes: List[str] = Field(default_factory=list)
    allowed_subject_id_types: List[str] = Field(default_factory=list)
    allowed_signing_algs: List[str] = Field(default_factory=lambda: ["EdDSA", "ES256"])
    max_validity_duration: Optional[str] = Field(None, examples=["P1Y"])
    fetch_type: str = "oneshot"
    max_fetch_frequency: Optional[str] = None
    data_life: Optional[str] = Field(None, examples=["P30D"])


class PolicyResponse(PolicyUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    partner_id: str
    version: int
    status: str  # pending | active | superseded | rejected
    awe_request_id: Optional[str] = None
    effective_from: Optional[datetime] = None
