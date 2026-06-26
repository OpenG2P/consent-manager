from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PartnerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    org_name: str = Field(..., min_length=1, max_length=255)
    audience: str = Field(..., min_length=1, max_length=255)
    controller_id: str = Field(..., min_length=1, max_length=255)
    jwks_url: Optional[str] = None


class PartnerUpdate(BaseModel):
    name: Optional[str] = None
    org_name: Optional[str] = None
    status: Optional[str] = None  # active | suspended
    jwks_url: Optional[str] = None


class PartnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    org_name: str
    audience: str
    controller_id: str
    status: str
    jwks_url: Optional[str] = None
    created_at: datetime


class KeyCreate(BaseModel):
    kid: str = Field(..., min_length=1, max_length=255)
    algorithm: str = Field(..., examples=["EdDSA", "ES256", "RS256"])
    public_key: str = Field(..., description="PEM-encoded public key")
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None


class KeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kid: str
    algorithm: str
    status: str
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None


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
    status: str
    effective_from: Optional[datetime] = None
