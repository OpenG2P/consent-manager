import threading
import time
from typing import Any, Optional


class TTLCache:
    """A tiny thread-safe, pod-local TTL cache.

    Used for partner keys/policies on the validation hot path. Each pod keeps
    its own copy; staleness after a key/policy change is bounded by the TTL,
    which is acceptable because onboarding changes are rare and a stale-but-valid
    key still verifies correctly. Safe across horizontally scaled replicas — no
    shared state, no coordination.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if now >= expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
