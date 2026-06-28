#!/usr/bin/env bash
# Run the Consent Manager sanity suite in-cluster (post-install/post-upgrade
# hook, or on demand).
#
#   SANITY_RUN_E2E=false (default) -> smoke + contract only (creates NO data).
#                       true       -> also the data-creating /validate round-trip.
#   SANITY_FAIL_ON_ERROR=false (default) -> always exit 0, so a failing run never
#                       fails the install/upgrade; read the logs for results.
#                       true       -> propagate pytest's exit code (CD gating).
#   SANITY_READINESS_TIMEOUT (default 180) -> wait for /ping before running.
set -o pipefail
cd /app

# --- wait for the Consent Manager to answer /ping before running ---
python - <<'PY'
import os, sys, time
import httpx

base = (os.environ.get("SANITY_BASE_URL") or "").rstrip("/")
if not base:
    sys.exit(0)
verify = (os.environ.get("SANITY_VERIFY_TLS", "true").lower() not in ("false", "0", "no"))
deadline = time.time() + int(os.environ.get("SANITY_READINESS_TIMEOUT", "180"))
url = base + "/ping"
while time.time() < deadline:
    try:
        if httpx.get(url, timeout=10, verify=verify).status_code == 200:
            print(f"[sanity] Consent Manager ready at {url}")
            sys.exit(0)
    except Exception:
        pass
    time.sleep(5)
print(f"[sanity] not ready after wait ({url}); running anyway")
PY

if [ "${SANITY_RUN_E2E}" = "true" ]; then
  echo "[sanity] running FULL suite (smoke + contract + e2e)"
  pytest "$@"
else
  echo "[sanity] running smoke + contract only (SANITY_RUN_E2E=false)"
  pytest -m "smoke or contract" "$@"
fi
rc=$?

if [ "${SANITY_FAIL_ON_ERROR}" = "true" ]; then
  exit $rc
fi
echo "[sanity] SANITY_FAIL_ON_ERROR=false -> exiting 0 (deploy not affected). pytest rc=${rc}"
exit 0
