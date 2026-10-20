# OpenG2P Consent Manager — Backend

The Policy Decision Point (PDP) for outbound data sharing, built on
[`openg2p-fastapi-common`](https://github.com/OpenG2P/openg2p-fastapi-common).

All documentation lives in the OpenG2P GitBook:

- **Design & API:** https://docs.openg2p.org/ → Consent Management
- **Development & local setup:** Consent Management → Development
- **Deployment:** Consent Management → Deployment

(Source in this repo: `openg2p-documentation/consent-management/`.)

## Consent claims and `/validate` (summary)

The consent is a compact JWS signed by the partner with its Partner-Management
key. Its claims carry `jti`, `aud`, `subject_id`, `purpose`, `fetch_type`,
`validity`, `issued_at`, and the data to share as either:

- `grants: [{data_controller, data_scopes}, ...]` — one consent, one grant per
  registry; or
- `data_controller` + `data_scopes` — the earlier single-registry form, treated
  as one grant.

`POST /consent/v1/validate` takes `consent_jws`, an optional `data_controller`
(the calling registry) and an optional `request_context {requested_scopes,
subject_id, use_case, purpose}`:

- With `grants`, `data_controller` is required and selects the grant; a
  controller without a grant is denied `controller_not_granted`. With the
  single-registry form, a `data_controller` that is given must match.
- What a partner may access is its policy in Partner Management (PM), one per
  controller, read from PM (`GET /policies/PARTNER_<AUD>?data_controller=…`)
  and cached. Effective scopes = grant ∩ that policy (∩ `requested_scopes`).
  No policy: `unknown_partner`; PM unreachable and nothing cached:
  `policy_unavailable`.
- Use-case mode (a configured receipt presenter sending
  `request_context.use_case`): the partner's use-case policy in PM applies
  instead; the use case must be granted (`use_case_not_granted`).
- `request_context.subject_id` of the consent subject's type but another value
  is denied `subject_mismatch`.
- Replay/idempotency is per (`jti`, `data_controller`): each registry gets its
  own decision and receipt.
- The response adds `data_controller`.

Partners, their keys and their policies are managed in Partner Management;
the Consent Manager keeps none.

Originated consents (`/consent-requests`) may carry `grants` too, and the
subject approves each controller's scopes. In the exchange role
(`receipt_issuer` and `receipt_presenters` set), a consent request (lifecycle
or partner portal) must name a `use_case` (`name@major`) granted by the
partner's use-case policy in PM (explicit grants are refused, `400`): its grants and purpose are the use case's,
read from the Composite (`CONSENT_MANAGER_COMPOSITE_API_URL`, `GET
/composite/v1/use-cases/{ref}`; unreachable → 503), and the consent is
presentable in use-case mode only for that use case. They cannot yet be presented at
`/validate`, which takes a partner-signed JWS only.

## Tests

`tests/` runs the services, controllers and migration against Postgres
(it wipes the database it is given):

```bash
pip install -e '.[test]'
CM_TEST_DB_DATASOURCE=postgresql+asyncpg://postgres@localhost:5432/cm_test pytest tests
```

The tests are skipped if the database cannot be reached.
