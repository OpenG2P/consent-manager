import logging
import time
from typing import Any, Dict, Optional

import httpx
from openg2p_fastapi_common.service import BaseService

from ..config import Settings

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


class AweClientError(Exception):
    """Raised when a call to AWE fails (network, non-2xx, or misconfiguration)."""

    def __init__(self, status_code: int, message: str, error_code: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class AweClient(BaseService):
    """Thin async client for the caller-facing AWE runtime endpoints CM needs.

    CM only ever *creates* approval requests; approvers act in AWE's own UI, and
    terminal outcomes come back via webhook. So this wraps a single endpoint —
    ``POST /v1/awe/requests`` — plus the client-credentials token fetch that
    authenticates it. Modelled on the registry's ``AweHelper``.
    """

    def __init__(self, name="", **kwargs):
        super().__init__(name, **kwargs)
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    async def _bearer(self) -> str:
        """Return a service bearer token, using a static token if configured or
        else a cached Keycloak client-credentials grant."""
        if _config.awe_static_token:
            return _config.awe_static_token

        now = time.time()
        if self._token and now < self._token_exp - 30:
            return self._token

        if not (_config.awe_token_url and _config.awe_client_id):
            raise AweClientError(500, "AWE service credentials are not configured")

        try:
            async with httpx.AsyncClient(timeout=_config.awe_http_timeout_seconds) as client:
                resp = await client.post(
                    _config.awe_token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": _config.awe_client_id,
                        "client_secret": _config.awe_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            raise AweClientError(502, f"Failed to obtain AWE service token: {exc}") from exc

        self._token = body["access_token"]
        self._token_exp = now + int(body.get("expires_in", 300))
        return self._token

    async def create_request(
        self,
        artifact_type: str,
        artifact_id: str,
        context: Dict[str, Any],
        requester: Optional[str] = None,
    ) -> str:
        """Submit an onboarding approval request to AWE. Returns the AWE
        ``request_id``. Raises AweClientError on any failure — the caller is
        expected to leave the partner un-onboarded (no partial state)."""
        if not _config.awe_base_url:
            raise AweClientError(500, "awe_base_url is not configured")

        payload = {
            "policy_key": _config.awe_partner_onboarding_policy_key,
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "context": context,
            "callback_url": _config.awe_callback_url or None,
            "callback_secret_id": _config.awe_callback_secret_id or None,
            "requester": requester,
        }
        url = f"{_config.awe_base_url.rstrip('/')}/v1/awe/requests"

        try:
            token = await self._bearer()
            async with httpx.AsyncClient(timeout=_config.awe_http_timeout_seconds) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        # Idempotent on the CM artifact id so a retried onboarding
                        # submit doesn't create duplicate AWE requests.
                        "Idempotency-Key": f"cm-partner-{artifact_id}",
                    },
                )
        except httpx.HTTPError as exc:
            raise AweClientError(502, f"AWE unreachable: {exc}") from exc

        if resp.status_code >= 300:
            body = _safe_json(resp)
            raise AweClientError(
                resp.status_code,
                body.get("message", resp.text),
                body.get("error_code", ""),
            )

        request_id = _safe_json(resp).get("request_id")
        if not request_id:
            raise AweClientError(502, "AWE response missing request_id")
        return request_id


def _safe_json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}
