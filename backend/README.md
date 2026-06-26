# OpenG2P Consent Manager — Backend

FastAPI service built on [`openg2p-fastapi-common`](https://github.com/OpenG2P/openg2p-fastapi-common).
It is the **Policy Decision Point (PDP)** for outbound data sharing: it verifies
partner-signed consent objects against each partner's onboarded policy and returns
the effective set of fields a data holder (PEP) may release.

The full design and API contract live in the GitBook under
`openg2p-documentation/consent-management/`.

## Layout

```
src/openg2p_consent_manager/
  config.py            Settings (env prefix CONSENT_MANAGER_)
  db.py                Shared async session factory
  auth.py              Subject OIDC bearer dependency (/my/*)
  models/              SQLAlchemy models (partner, consent, audit)
  schemas/             Pydantic request/response models
  services/            crypto · partner · policy · receipt · verification · consent · lifecycle
  controllers/         verification · well-known · partner · lifecycle · subject
  app.py               Initializer (wires services + controllers, migrations)
  main.py              ASGI entrypoint (gunicorn/uvicorn)
  expire.py            Standalone expiry runner (for a CronJob)
```

## Endpoints (prefix `/consent/v1`)

| Path | Method | Purpose |
| --- | --- | --- |
| `/validate` | POST | Verify an embedded consent object → decision + effective fields (hot path) |
| `/consents/{id}/status` | GET | OCSP-like status check |
| `/receipts/{id}` | GET | Fetch a signed receipt |
| `/.well-known/jwks.json` | GET | CM signing public keys |
| `/partners`, `/partners/{id}` | POST/GET/PATCH | Partner onboarding (admin) |
| `/partners/{id}/keys`, `/keys/{kid}` | POST/DELETE | Partner key management |
| `/partners/{id}/policy` | PUT/GET | Versioned policy |
| `/consent-requests…` | POST/GET | Origination flow (request, authenticate, approve, deny) |
| `/consents/{id}/revoke` | POST | Revoke |
| `/my/consents`, `/my/receipts/{id}` | GET | Subject rights (GDPR) |

## Run locally

```bash
cp .env.example .env          # adjust DB + signing key
pip install -e .              # plus openg2p-fastapi-common
python -m openg2p_consent_manager.main migrate
uvicorn openg2p_consent_manager.main:app --reload
```

Or via Docker Compose from the repo root: `docker compose up --build`.

## Horizontal scalability

* **Stateless** — no per-pod state; any replica serves any request. Scale by adding
  pods/workers behind a load balancer; no session affinity needed.
* **Shared Postgres** with connection pooling from the framework engine. Size
  `max_connections ≳ pods × workers × pool_size + headroom`.
* **No in-process scheduler** — expiry runs via `python -m openg2p_consent_manager.expire`
  as an external CronJob, so it fires once per tick regardless of replica count; the
  hot path also lazily expires on read.
* **Hot-path cache** — partner keys/policies are cached per pod with a short TTL to
  keep `validate` cheap under high request rates.
* **Idempotent** — re-validating the same consent object (`jti`) returns the same
  decision instead of minting duplicates.
