# OpenG2P Consent Manager

The **Consent Manager** is the Policy Decision Point (PDP) for outbound data sharing in OpenG2P.
A single instance is shared across all data-holding modules (registry, PBMS, …): a partner embeds
a signed consent object in its request, the module forwards it to the Consent Manager, and the
service verifies the signature against the partner's onboarded keys, evaluates it against the
partner's policy, and returns the exact set of fields that may be released.

This chart deploys the API (horizontally autoscaled, stateless), provisions its PostgreSQL
database, optionally provisions its Keycloak client and admin role, and runs a periodic
consent-expiry job.

Full documentation: [docs.openg2p.org → Consent Management](https://docs.openg2p.org/).
