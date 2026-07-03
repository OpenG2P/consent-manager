// Types mirroring the Consent Manager backend schemas (/consent/v1/*).
// Kept intentionally close to the Pydantic models so the client stays honest.

export type PartnerStatus = "active" | "suspended";

// Approval fields are populated once partner-onboarding is wired to the shared
// Approval Workflow Engine. They are optional so the UI degrades gracefully
// against a backend that does not yet emit them.
export type ApprovalStatus = "not_required" | "pending" | "approved" | "rejected";

export interface Partner {
  id: string;
  name: string;
  org_name: string;
  audience: string;
  controller_id: string;
  // Reference used to fetch this partner's keys from Partner Management (PM).
  // Signing keys live in PM, not CM. Falls back to `audience` when unset.
  partner_mgmt_id?: string | null;
  status: PartnerStatus;
  created_at?: string;
  approval_status?: ApprovalStatus;
  awe_request_id?: string | null;
}

export interface PartnerCreate {
  name: string;
  org_name: string;
  audience: string;
  controller_id: string;
  partner_mgmt_id?: string | null;
}

export interface PartnerUpdate {
  name?: string;
  org_name?: string;
  status?: PartnerStatus;
  partner_mgmt_id?: string | null;
}

export type FetchType = "oneshot" | "periodic";

// Durations are ISO-8601 duration strings (e.g. "P1Y", "P30D", "PT12H"),
// matching the backend. max_fetch_frequency is likewise a string (e.g. "P1D").
export interface PolicyUpsert {
  allowed_data_scopes: string[];
  allowed_purposes: string[];
  allowed_subject_id_types: string[];
  allowed_signing_algs: string[];
  max_validity_duration?: string | null;
  fetch_type: FetchType;
  max_fetch_frequency?: string | null;
  data_life?: string | null;
}

export interface PartnerPolicy extends PolicyUpsert {
  id: string;
  partner_id: string;
  version: number;
  status: string;
  effective_from?: string | null;
}

// ── Subject rights (transparency dashboard) ──────────────────────────────
// Backed by ArtefactResponse. `purpose` is a structured object; the registry
// decides its shape, so we render defensively.
export type ConsentStatus = "active" | "revoked" | "expired" | "pending";

export interface Purpose {
  code?: string;
  name?: string;
  description?: string;
  [k: string]: unknown;
}

export interface Artefact {
  id: string;
  consent_id?: string | null;
  subject_id_type: string;
  subject_id_value: string;
  partner_id: string;
  purpose: Purpose;
  effective_data_scopes: string[];
  status: ConsentStatus;
  source: string;
  valid_from: string;
  valid_until: string;
  created_at: string;
  revoked_at?: string | null;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface RevokeResponse {
  consent_id: string;
  status: string;
  revoked_at: string;
}

// ── Consent-request (originate / redirect flow) ──────────────────────────
export interface ConsentRequest {
  id: string;
  subject_id_type: string;
  subject_id_value: string;
  partner_id: string;
  purpose: Purpose;
  requested_scopes: string[];
  status: string; // created | authenticated | approved | denied | expired
  valid_from?: string | null;
  valid_until?: string | null;
  created_at: string;
}
