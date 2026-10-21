// Types mirroring the Consent Manager backend schemas (/consent/v1/*).
// Kept intentionally close to the Pydantic models so the client stays honest.

// ── Decision log (admin status/audit view) ───────────────────────────────
export interface DecisionLog {
  id: string;
  // The partner's audience (e.g. bank-a), as in Partner Management.
  partner_id?: string | null;
  consent_id?: string | null;
  object_jti?: string | null;
  data_controller?: string | null;
  decision: "permit" | "deny";
  reason_code: string;
  detail?: string | null;
  policy_version?: number | null;
  // The PM policy applied: PM's id of that version, and its kind:key
  // ("use_case:loan-profile@1" / "data_controller:farmer-registry").
  policy_id?: string | null;
  policy_ref?: string | null;
  created_at: string;
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
  controller_id?: string | null;
  purpose: Purpose;
  effective_data_scopes: string[];
  grants?: ArtefactGrant[] | null;
  // The PM policy the consent was made under (all grants' when they share one).
  policy_version?: number | null;
  policy_id?: string | null;
  policy_ref?: string | null;
  status: ConsentStatus;
  source: string;
  valid_from: string;
  valid_until: string;
  created_at: string;
  revoked_at?: string | null;
}

// One grant per data controller (registry) in a consent.
export interface Grant {
  data_controller: string;
  data_scopes: string[];
}

export interface ArtefactGrant extends Grant {
  effective_data_scopes: string[];
  granted_scopes?: string[];
  policy_version?: number | null;
  policy_id?: string | null;
  policy_ref?: string | null;
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
  controller_id?: string | null;
  purpose: Purpose;
  requested_scopes: string[];
  // Present when the request spans several controllers (one grant each).
  grants?: Grant[] | null;
  status: string; // created | authenticated | approved | denied | expired
  valid_from?: string | null;
  valid_until?: string | null;
  created_at: string;
}

// ── Consent verifications (assisted consent, staff check of the signed form) ──
// /consent/v1/verifications — a partner user raised the request in the partner
// portal and uploaded the evidence; staff approve (creates the consent) or reject.
export type VerificationStatus = "pending_verification" | "approved" | "rejected";

export interface VerificationEvidence {
  id: string;
  kind: "signed_form" | "other" | string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by?: string | null;
  uploaded_at: string;
}

export interface VerificationRequest {
  id: string;
  status: string;
  method?: string | null;
  use_case?: string | null;
  subject_id: { type: string; value: string };
  // Other identifiers of the subject (e.g. the Farmer ID); the approver checks
  // them in the registry.
  subject_identifiers?: { type: string; value: string }[];
  purpose: Purpose | string;
  grants: Grant[];
  valid_from?: string | null;
  valid_until?: string | null;
  created_by?: string | null;
  created_at: string;
  submitted_at?: string | null;
  verified_by?: string | null;
  verified_at?: string | null;
  verification_note?: string | null;
  consent_id?: string | null;
  partner_audience?: string | null;
  // The subject's latest national-ID login (eSignet), if the CM has it on.
  subject_authentication?: {
    status: string;
    error?: string | null;
    provider?: string | null;
    method?: string | null;
    acr?: string | null;
    authenticated_at?: string | null;
    started_by?: string | null;
    // As the identity provider returned them at this login, not the registry's.
    demographics?: Record<string, unknown> | null;
    demographics_source?: string | null;
    previous_success?: { authenticated_at?: string | null; method?: string | null } | null;
  } | null;
  evidence?: VerificationEvidence[];
}

export interface OffsetPage<T> {
  total: number;
  items: T[];
}
