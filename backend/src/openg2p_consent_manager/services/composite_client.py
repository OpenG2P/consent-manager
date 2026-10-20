"""Use cases, read from the Composite (exchange role).

At the Exchange a consent made through the partner portal or the lifecycle API
is made for a use case (``name@major``). What it grants — the purpose and the
scopes per registry — is the use case's, as the Composite publishes it:

    GET {composite_api_url}/composite/v1/use-cases/{name@major}

(``purpose``; ``consent_scopes``: {controller: {required, optional}};
``consent_grants_needed``: every registry the use case queries). Answers are
reused for ``composite_use_case_cache_ttl_seconds``. When the Composite cannot
be reached, nothing stale is served: the caller fails closed
(``CompositeUnavailable``).
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import httpx
from openg2p_fastapi_common.service import BaseService

from ..config import Settings

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)

USE_CASE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*@[0-9]+$")


def consent_by_use_case() -> bool:
    """Exchange role (this CM issues consent tokens to the Composite): consents
    made here through the portal or the lifecycle API are made for a use case."""
    return bool(_config.receipt_issuer and _config.receipt_presenters)


EXCHANGE_NEEDS_USE_CASE = (
    "at the Exchange, consents are made for a use case: send 'use_case' (name@major) "
    "without grants, data_controller or requested_scopes"
)


class CompositeUnavailable(Exception):
    """The Composite is not configured, cannot be reached or answered wrongly."""


@dataclass(frozen=True)
class UseCase:
    """A published use case, as far as a consent is concerned."""

    ref: str  # name@major
    title: Optional[str]
    description: Optional[str]
    purpose: Optional[str]
    # [{"data_controller", "data_scopes", "required_scopes", "optional_scopes"}]
    # for every registry whose sources name scopes (data_scopes = required ∪ optional).
    grants: list = field(default_factory=list)
    # Registries the use case queries without naming scopes (it takes the grant
    # as it is): a consent cannot be made for it by use case.
    unscoped_controllers: list = field(default_factory=list)
    subject_id_types: list = field(default_factory=list)

    @classmethod
    def from_composite(cls, data: dict) -> "UseCase":
        scopes = data.get("consent_scopes") or {}
        grants = []
        for controller in sorted(scopes):
            entry = scopes[controller] or {}
            required = sorted({str(s) for s in entry.get("required") or []})
            optional = sorted({str(s) for s in entry.get("optional") or []} - set(required))
            if required or optional:
                grants.append(
                    {
                        "data_controller": controller,
                        "data_scopes": sorted(set(required) | set(optional)),
                        "required_scopes": required,
                        "optional_scopes": optional,
                    }
                )
        scoped = {g["data_controller"] for g in grants}
        needed = [str(c) for c in data.get("consent_grants_needed") or []]
        subject = ((data.get("input") or {}).get("subject") or {}).get("id_types") or []
        return cls(
            ref=str(data["use_case"]),
            title=data.get("title") or None,
            description=data.get("description") or None,
            purpose=data.get("purpose") or None,
            grants=grants,
            unscoped_controllers=sorted(set(needed) - scoped),
            subject_id_types=[str(t) for t in subject],
        )


class CompositeClient(BaseService):
    """Cached reader of use cases from the Composite."""

    def __init__(self, name="", clock=time.monotonic, **kwargs):
        super().__init__(name, **kwargs)
        self._clock = clock
        self._cache: dict[str, tuple[float, Optional[UseCase]]] = {}
        # Swappable in tests (an httpx.MockTransport standing in for the Composite).
        self.transport: Optional[httpx.AsyncBaseTransport] = None

    async def get_use_case(self, ref: str) -> Optional[UseCase]:
        """The published use case ``ref`` (name@major); None when the Composite
        publishes none by that reference. Raises CompositeUnavailable."""
        now = self._clock()
        cached = self._cache.get(ref)
        if cached is not None and now - cached[0] < _config.composite_use_case_cache_ttl_seconds:
            return cached[1]
        base = (_config.composite_api_url or "").rstrip("/")
        if not base:
            raise CompositeUnavailable("composite_api_url is not configured")
        url = f"{base}/composite/v1/use-cases/{quote(ref, safe='@')}"
        try:
            async with httpx.AsyncClient(
                timeout=_config.composite_fetch_timeout_seconds, transport=self.transport
            ) as client:
                resp = await client.get(url)
        except Exception as exc:
            _logger.error("Composite use case %s: request failed: %r", ref, exc)
            raise CompositeUnavailable(f"request failed: {exc!r}") from exc
        if resp.status_code in (400, 404):
            use_case = None
        elif resp.status_code != 200:
            _logger.error("Composite use case %s: HTTP %s", ref, resp.status_code)
            raise CompositeUnavailable(f"HTTP {resp.status_code}")
        else:
            try:
                use_case = UseCase.from_composite(resp.json())
            except Exception as exc:
                _logger.error("Composite use case %s: bad response body: %r", ref, exc)
                raise CompositeUnavailable(f"bad response body: {exc!r}") from exc
            if use_case.ref != ref:
                # e.g. name@1 asked, another major served: not this use case.
                use_case = None
        self._cache[ref] = (now, use_case)
        return use_case

    def invalidate(self) -> None:
        self._cache.clear()
