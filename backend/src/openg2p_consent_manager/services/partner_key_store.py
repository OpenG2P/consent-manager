import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import quote

import httpx
from openg2p_fastapi_common.service import BaseService

from ..config import Settings

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)

# A parsed, cached set of keys for one PM reference_id.
#   keys: {kid: {"public_key": pem, "algorithm": alg}}  (None keys => negative cache)
#   fetched_at: monotonic time of the last successful/negative fetch
#   soft_expiry / hard_expiry: monotonic deadlines
#   last_attempt: monotonic time of the last fetch attempt (for the cooldown)
class _Entry:
    __slots__ = ("keys", "fetched_at", "soft_expiry", "hard_expiry", "last_attempt")

    def __init__(self, keys, fetched_at, soft_expiry, hard_expiry):
        self.keys: Optional[Dict[str, dict]] = keys
        self.fetched_at = fetched_at
        self.soft_expiry = soft_expiry
        self.hard_expiry = hard_expiry
        self.last_attempt = fetched_at


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class PartnerMgmtKeyStore(BaseService):
    """Fetches partner public keys from the Partner Management (PM) service and
    caches them per pod with a soft/hard/negative TTL, single-flight, and an
    unknown-kid refresh — mirroring the commons ``PartnerMgmtKeyStore`` discipline
    (CM keeps its own because it keys verification on audience, not the commons
    mnemonic/JWS path).

    Source of truth is PM: ``GET {api}/keys/{reference_id}`` →
    ``{"keys": [{"kid","algorithm","public_key"(PEM),"not_before","not_after"}]}``.
    A 404 means "no keys" and is cached briefly and treated as reject upstream.
    """

    def __init__(self, name="", **kwargs):
        super().__init__(name, **kwargs)
        self._clock = time.monotonic
        self._cache: Dict[str, _Entry] = {}
        self._cache_lock = threading.Lock()
        self._flight: Dict[str, asyncio.Lock] = {}

    async def get_key(self, reference_id: str, kid: str) -> Optional[dict]:
        """Return ``{"public_key","algorithm"}`` for one (reference_id, kid), or
        None if unavailable. An unknown kid triggers a rate-limited refresh so a
        just-rotated key is picked up without waiting for the soft TTL."""
        keys = await self.get_keys(reference_id, wanted_kid=kid)
        if not keys:
            return None
        return keys.get(kid)

    async def get_keys(
        self, reference_id: str, wanted_kid: Optional[str] = None
    ) -> Optional[Dict[str, dict]]:
        """Return ``{kid: {"public_key","algorithm"}}`` for a partner, or None."""
        if not _config.partner_mgmt_api_url:
            _logger.warning(
                "partner_mgmt_api_url is not configured — cannot fetch partner keys"
            )
            return None

        now = self._clock()
        entry = self._get_entry(reference_id)

        if entry is not None and now < entry.soft_expiry:
            # Fresh. Only refetch early if a wanted kid is missing (rotation) and
            # we are past the refresh cooldown.
            if (
                wanted_kid
                and (entry.keys is None or wanted_kid not in entry.keys)
                and (now - entry.last_attempt) >= _config.partner_key_refresh_cooldown_seconds
            ):
                return await self._refresh(reference_id, entry)
            return entry.keys

        # Soft-expired or absent → refresh (single-flight), with hard-TTL fallback.
        return await self._refresh(reference_id, entry)

    def invalidate(self, reference_id: Optional[str] = None) -> None:
        with self._cache_lock:
            if reference_id is None:
                self._cache.clear()
            else:
                self._cache.pop(reference_id, None)

    # ── internals ────────────────────────────────────────────────────────────

    def _get_entry(self, reference_id: str) -> Optional[_Entry]:
        with self._cache_lock:
            return self._cache.get(reference_id)

    def _flight_lock(self, reference_id: str) -> asyncio.Lock:
        with self._cache_lock:
            lock = self._flight.get(reference_id)
            if lock is None:
                lock = asyncio.Lock()
                self._flight[reference_id] = lock
            return lock

    async def _refresh(
        self, reference_id: str, stale: Optional[_Entry]
    ) -> Optional[Dict[str, dict]]:
        lock = self._flight_lock(reference_id)
        async with lock:
            # Another coroutine may have refreshed while we waited for the lock.
            current = self._get_entry(reference_id)
            now = self._clock()
            if current is not None and current is not stale and now < current.soft_expiry:
                return current.keys

            try:
                keys, max_age = await self._fetch(reference_id)
            except _NotFound:
                self._store(reference_id, None, _config.partner_key_negative_ttl_seconds)
                return None
            except Exception as exc:  # network/parse error — serve stale within hard TTL
                if stale is not None and self._clock() < stale.hard_expiry:
                    _logger.warning(
                        "PM key fetch for %s failed (%s); serving stale keys within hard TTL",
                        reference_id, exc,
                    )
                    stale.last_attempt = self._clock()
                    return stale.keys
                _logger.error(
                    "PM key fetch for %s failed (%s) and no usable cache — failing closed",
                    reference_id, exc,
                )
                return None

            soft = _config.partner_key_cache_ttl_seconds
            if max_age is not None:
                soft = min(soft, max_age)
            self._store(reference_id, keys, soft)
            return keys

    def _store(self, reference_id: str, keys: Optional[Dict[str, dict]], soft_ttl: int) -> None:
        now = self._clock()
        entry = _Entry(
            keys=keys,
            fetched_at=now,
            soft_expiry=now + soft_ttl,
            hard_expiry=now + _config.partner_key_hard_ttl_seconds,
        )
        with self._cache_lock:
            self._cache[reference_id] = entry

    async def _fetch(self, reference_id: str):
        """GET {api}/keys/{reference_id} → ({kid: {...}}, max_age|None).
        Raises _NotFound on 404, or an exception on any other failure."""
        url = (
            _config.partner_mgmt_api_url.rstrip("/")
            + "/keys/"
            + quote(reference_id, safe="")
        )
        async with httpx.AsyncClient(
            timeout=_config.partner_key_fetch_timeout_seconds
        ) as client:
            resp = await client.get(url)
        if resp.status_code == 404:
            raise _NotFound()
        resp.raise_for_status()
        document = resp.json()
        return self._parse(document), _parse_max_age(resp.headers.get("Cache-Control"))

    @staticmethod
    def _parse(document: dict) -> Dict[str, dict]:
        now = datetime.now(timezone.utc)
        keys: Dict[str, dict] = {}
        for item in document.get("keys", []):
            kid = item.get("kid")
            pem = item.get("public_key")
            alg = item.get("algorithm")
            if not (kid and pem and alg):
                continue
            nb = item.get("not_before")
            na = item.get("not_after")
            if nb and now < _aware(_parse_dt(nb)):
                continue
            if na and now > _aware(_parse_dt(na)):
                continue
            keys[kid] = {"public_key": pem, "algorithm": alg}
        return keys


class _NotFound(Exception):
    """Internal: PM returned 404 (unknown/disabled partner or no active keys)."""


_MAX_AGE_RE = re.compile(r"max-age\s*=\s*(\d+)", re.IGNORECASE)


def _parse_max_age(cache_control: Optional[str]) -> Optional[int]:
    if not cache_control:
        return None
    m = _MAX_AGE_RE.search(cache_control)
    return int(m.group(1)) if m else None


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
