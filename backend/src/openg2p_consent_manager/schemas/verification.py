from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .common import ReasonCode, SubjectId


class ConsentObjectSignature(BaseModel):
    algorithm: str = Field(..., examples=["EdDSA"])
    kid: str
    value: str  # base64url signature over the canonical object (sans signature)


class ConsentObjectValidity(BaseModel):
    valid_from: datetime
    valid_until: datetime


class ConsentObject(BaseModel):
    """The partner-signed JSON-LD object embedded in a registry request."""

    jti: str
    subject_id: SubjectId
    data_controller: str
    aud: str
    purpose: Dict[str, Any]
    data_scopes: List[str]
    fetch_type: str = "oneshot"
    validity: ConsentObjectValidity
    issued_at: datetime
    signature: ConsentObjectSignature

    # Tolerate JSON-LD framing keys (@context/@type) and any extra attributes.
    model_config = {"extra": "allow"}


class RequestContext(BaseModel):
    requested_scopes: Optional[List[str]] = None
    subject_id: Optional[SubjectId] = None


class ValidateRequest(BaseModel):
    consent_object: ConsentObject
    partner_id: str
    request_context: Optional[RequestContext] = None


class DecisionLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    partner_id: Optional[str] = None
    consent_id: Optional[str] = None
    object_jti: Optional[str] = None
    decision: str
    reason_code: str
    detail: Optional[str] = None
    policy_version: Optional[int] = None
    created_at: datetime


class Decision(BaseModel):
    decision: str  # permit | deny
    reason_code: ReasonCode
    detail: Optional[str] = None
    consent_id: Optional[str] = None
    receipt_id: Optional[str] = None
    subject_id: Optional[SubjectId] = None
    effective_data_scopes: Optional[List[str]] = None
    valid_until: Optional[datetime] = None
    policy_version: Optional[int] = None
    evaluated_at: datetime
