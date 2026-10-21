from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import SubjectId
from .verification import ConsentGrant


class ConsentRequestCreate(BaseModel):
    """An originated consent request for the partner ``partner_id`` (its
    audience, e.g. bank-a). Either ``data_controller`` + ``requested_scopes``
    (one controller) or ``grants`` (several controllers). Each is checked
    against the partner's policy for that controller in Partner Management.

    Exchange role: ``use_case`` (``name@major``) instead — the request is made
    for that use case, for which the partner must have a policy in Partner
    Management; the grants and purpose are the Composite's use case
    (``purpose``, if given, must be the use case's)."""

    subject_id: SubjectId
    partner_id: str = Field(..., min_length=1, examples=["bank-a"])
    purpose: Optional[Dict[str, Any]] = None
    data_controller: Optional[str] = Field(None, min_length=1)
    requested_scopes: Optional[List[str]] = Field(None, min_length=1)
    grants: Optional[List[ConsentGrant]] = Field(None, min_length=1)
    validity: Optional[Dict[str, datetime]] = None  # {valid_from, valid_until}
    use_case: Optional[str] = Field(None, max_length=255, examples=["loan-profile@1"])

    @model_validator(mode="after")
    def _one_shape(self):
        if self.use_case is not None:
            if (
                self.grants is not None
                or self.requested_scopes is not None
                or self.data_controller is not None
            ):
                raise ValueError(
                    "at the Exchange, consents are made for a use case: leave out "
                    "'grants', 'data_controller' and 'requested_scopes'"
                )
            return self
        if self.purpose is None:
            raise ValueError("'purpose' is required")
        if (self.requested_scopes is None) == (self.grants is None):
            raise ValueError("give exactly one of 'requested_scopes' or 'grants'")
        if self.requested_scopes is not None and not self.data_controller:
            raise ValueError("'requested_scopes' needs 'data_controller'")
        if self.grants is not None and self.data_controller is not None:
            raise ValueError("'data_controller' goes in each grant, not beside 'grants'")
        if self.grants is not None:
            controllers = [g.data_controller for g in self.grants]
            if len(controllers) != len(set(controllers)):
                raise ValueError("'grants' names the same data_controller more than once")
            if any(not g.data_scopes for g in self.grants):
                raise ValueError("each grant needs at least one data scope")
        return self


class ConsentRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_id_type: str
    subject_id_value: str
    partner_id: str
    controller_id: Optional[str] = None
    purpose: Dict[str, Any]
    requested_scopes: List[str]
    grants: Optional[List[Dict[str, Any]]] = None
    use_case: Optional[str] = None
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
    """The subject's approval. For a single-controller request, ``granted_scopes``.
    For a grants request, ``grants`` — the subject approves each controller's
    scopes; a controller left out (or with no scopes) is declined. A grants
    request approved with ``granted_scopes`` applies them to every grant."""

    granted_scopes: Optional[List[str]] = Field(None, min_length=1)
    grants: Optional[List[ConsentGrant]] = None

    @model_validator(mode="after")
    def _one_shape(self):
        if (self.granted_scopes is None) == (self.grants is None):
            raise ValueError("give exactly one of 'granted_scopes' or 'grants'")
        return self


class ArtefactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    consent_id: Optional[str] = None
    subject_id_type: str
    subject_id_value: str
    partner_id: str
    controller_id: Optional[str] = None
    purpose: Dict[str, Any]
    effective_data_scopes: List[str]
    # Originated grants consent: one entry per approved controller.
    grants: Optional[List[Dict[str, Any]]] = None
    # How the subject confirmed (originated consents), and its request.
    assurance: Optional[Dict[str, Any]] = None
    consent_request_id: Optional[str] = None
    # Exchange role: the use case the consent was made for (presentable only for it).
    use_case: Optional[str] = None
    # The PM policy the consent was made under (all grants' when they share
    # one): version, PM's id of that version and its kind:key.
    policy_version: Optional[int] = None
    policy_id: Optional[str] = None
    policy_ref: Optional[str] = None
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
