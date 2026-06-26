from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import SubjectId


class ConsentRequestCreate(BaseModel):
    subject_id: SubjectId
    partner_id: str
    purpose: Dict[str, Any]
    requested_scopes: List[str] = Field(..., min_length=1)
    validity: Optional[Dict[str, datetime]] = None  # {valid_from, valid_until}


class ConsentRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_id_type: str
    subject_id_value: str
    partner_id: str
    purpose: Dict[str, Any]
    requested_scopes: List[str]
    status: str
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    created_at: datetime


class AuthenticateRequest(BaseModel):
    id_token: str


class AuthenticateResponse(BaseModel):
    request_id: str
    auth_context_id: str
    token_validated: bool
    auth_method: Optional[str] = None


class ApproveRequest(BaseModel):
    granted_scopes: List[str] = Field(..., min_length=1)


class ArtefactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    consent_id: Optional[str] = None
    subject_id_type: str
    subject_id_value: str
    partner_id: str
    purpose: Dict[str, Any]
    effective_data_scopes: List[str]
    status: str
    source: str
    valid_from: datetime
    valid_until: datetime
    created_at: datetime
    revoked_at: Optional[datetime] = None


class DenyRequest(BaseModel):
    reason: Optional[str] = None


class RevokeRequest(BaseModel):
    reason: Optional[str] = None
    originated_by: str = "controller"  # subject | controller | partner


class RevokeResponse(BaseModel):
    consent_id: str
    status: str
    revoked_at: datetime
