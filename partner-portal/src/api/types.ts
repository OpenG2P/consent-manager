// Types for the Consent Manager partner-portal API (/consent/v1/partner-portal/*)
// and the composite's public use-case list. Shapes follow the scenario-1 contract.

export interface Me {
  username: string;
  name?: string | null;
  partner_id: string;
  roles: string[];
}

// One active scope policy of this partner (set in Partner Management): what it
// may ask for from one registry.
export interface ScopePolicy {
  data_controller: string;
  allowed_data_scopes: string[];
  allowed_purposes: string[];
  allowed_subject_id_types: string[];
  // ISO-8601 duration (e.g. "P1Y"); null = no limit beyond the default.
  max_validity_duration: string | null;
  policy_version: number;
}

// What a consent for a use case grants from one registry (data_scopes =
// required + optional).
export interface UseCaseGrant {
  data_controller: string;
  data_scopes: string[];
  required_scopes: string[];
  optional_scopes: string[];
}

// A use case granted to this partner by its use-case policy in Partner
// Management (at the Exchange), with its purpose and data per registry from the
// Composite. available=false: no consent can be made for it now (see detail).
export interface UseCaseAccess {
  use_case: string; // name@major
  title?: string | null;
  description?: string | null;
  purpose?: string | null;
  grants: UseCaseGrant[];
  subject_id_types: string[];
  allowed_purposes: string[];
  allowed_subject_id_types: string[];
  max_validity_duration: string | null;
  policy_version: number;
  available: boolean;
  detail?: string | null;
}

// GET /access — what the partner may ask for. consent_by "use_case" (at the
// Exchange): a request names one of use_cases. "scopes": a request names
// registries and data, within scope_policies.
export type ConsentBy = "use_case" | "scopes";

export interface PartnerAccess {
  consent_by: ConsentBy;
  scope_policies: ScopePolicy[];
  use_cases: UseCaseAccess[];
}

export interface SubjectId {
  type: string;
  value: string;
}

// The registry decides the purpose's shape beyond `code`, so render defensively.
export interface Purpose {
  code?: string;
  name?: string;
  description?: string;
  [k: string]: unknown;
}

export interface Grant {
  data_controller: string;
  data_scopes: string[];
}

export type RequestStatus =
  | "pending"
  | "pending_verification"
  | "approved"
  | "rejected"
  | "cancelled"
  | "denied"
  | "expired";

export const REQUEST_STATUSES: RequestStatus[] = [
  "pending",
  "pending_verification",
  "approved",
  "rejected",
  "cancelled",
  "denied",
  "expired",
];

export interface Evidence {
  id: string;
  kind: "signed_form" | "other" | string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by?: string | null;
  uploaded_at: string;
}

export interface ConsentRequest {
  id: string;
  status: RequestStatus | string;
  method?: string | null;
  use_case?: string | null;
  subject_id: SubjectId;
  // Other identifiers of the subject, e.g. the Farmer ID.
  subject_identifiers?: SubjectId[];
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
  // The subject's latest national-ID login (null: none started).
  subject_authentication?: SubjectAuth | null;
  // Present on GET /consent-requests/{id}.
  evidence?: Evidence[];
}

export interface SubjectAuth {
  authentication_id: string;
  status: "pending" | "processing" | "success" | "failed" | "expired" | string;
  error?: string | null;
  started_by?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  provider?: string | null;
  method?: string | null;
  acr?: string | null;
  authenticated_at?: string | null;
  // As the identity provider returned them at this login (e.g. the name as per
  // the national ID), not the registry's record.
  demographics?: Record<string, unknown> | null;
  demographics_source?: string | null;
  // A later attempt failed or is running, but an earlier one succeeded.
  previous_success?: { authenticated_at?: string | null; method?: string | null } | null;
}

export interface SubjectAuthConfig {
  enabled: boolean;
  provider_name?: string | null;
  id_types: string[];
}

export interface RequestSettings {
  consent_by: ConsentBy;
  required_subject_identifiers: string[];
  subject_auth: SubjectAuthConfig;
}

export interface SubjectAuthStart {
  authentication_id: string;
  authorization_url: string;
  provider_name: string;
  expires_at: string;
}

// With grants: purpose and grants required, use_case a label. At the Exchange
// (consent_by "use_case"): use_case only — the grants and purpose are the use case's.
export interface ConsentRequestCreate {
  subject_id: SubjectId;
  subject_identifiers?: SubjectId[];
  purpose?: { code: string };
  grants?: Grant[];
  validity?: { valid_from?: string; valid_until?: string };
  use_case?: string;
}

export interface Page<T> {
  total: number;
  items: T[];
}

export type ConsentStatus = "active" | "revoked" | "expired";
export const CONSENT_STATUSES: ConsentStatus[] = ["active", "revoked", "expired"];

export interface ConsentGrant extends Grant {
  effective_data_scopes: string[];
}

// How the subject's consent was confirmed, e.g.
// {"method":"assisted","evidence":["signed_form"],"verified_by":"…","verified_at":"…","subject_authenticated":false}
export interface Assurance {
  method?: string;
  evidence?: string[];
  verified_by?: string;
  verified_at?: string;
  subject_authenticated?: boolean;
  [k: string]: unknown;
}

export interface Consent {
  consent_id: string;
  status: ConsentStatus | string;
  subject_id: SubjectId;
  subject_identifiers?: SubjectId[];
  purpose: Purpose | string;
  grants: ConsentGrant[];
  valid_from?: string | null;
  valid_until?: string | null;
  assurance?: Assurance | null;
  use_case?: string | null;
  consent_request_id?: string | null;
  created_at: string;
  revoked_at?: string | null;
}

// ── Composite: GET {compositeUrl}/composite/v1/use-cases (public) ──────────
export interface ConsentScopes {
  required: string[];
  optional: string[];
}

export interface UseCase {
  use_case: string; // ref, e.g. "loan-profile@1"
  name: string;
  version: string;
  status?: string;
  title?: string;
  description?: string;
  purpose?: string;
  consent?: { required?: boolean };
  input?: { subject?: { id_types?: string[] } };
  consent_scopes?: Record<string, ConsentScopes>;
}
