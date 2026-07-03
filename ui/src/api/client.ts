// Thin typed fetch wrapper over the Consent Manager REST API.
// Every path is rooted at /consent/v1 (the backend router prefix). Admin calls
// carry the Keycloak bearer token; the subject/consent-request flow reuses the
// authenticated subject's token.
import { getConfig, getToken, refreshToken } from "../auth";
import type {
  Artefact,
  ConsentRequest,
  Paginated,
  Partner,
  PartnerCreate,
  PartnerPolicy,
  PartnerUpdate,
  PolicyUpsert,
  RevokeResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  reason?: string;
  constructor(status: number, message: string, reason?: string) {
    super(message);
    this.status = status;
    this.reason = reason;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  await refreshToken();
  const base = getConfig().apiBaseUrl.replace(/\/$/, "");
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(init.headers ?? {}),
    },
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? JSON.parse(text) : undefined;
  if (!res.ok) {
    const detail = body?.detail ?? body?.error ?? body?.message ?? res.statusText;
    const reason = body?.reason_code ?? body?.reason;
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail), reason);
  }
  return body as T;
}

const V1 = "/consent/v1";

export const api = {
  // ── Partners (admin) ───────────────────────────────────────────────
  listPartners: () => request<Partner[]>(`${V1}/partners`),
  getPartner: (id: string) => request<Partner>(`${V1}/partners/${id}`),
  createPartner: (data: PartnerCreate) =>
    request<Partner>(`${V1}/partners`, { method: "POST", body: JSON.stringify(data) }),
  updatePartner: (id: string, data: PartnerUpdate) =>
    request<Partner>(`${V1}/partners/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  // Policy
  getPolicy: (id: string) => request<PartnerPolicy>(`${V1}/partners/${id}/policy`),
  putPolicy: (id: string, data: PolicyUpsert) =>
    request<PartnerPolicy>(`${V1}/partners/${id}/policy`, { method: "PUT", body: JSON.stringify(data) }),

  // ── Subject rights (transparency dashboard) ────────────────────────
  myConsents: (status?: string) =>
    request<Paginated<Artefact>>(
      `${V1}/my/consents${status ? `?status=${encodeURIComponent(status)}` : ""}`
    ).then((p) => p.items),
  myConsent: (id: string) => request<Artefact>(`${V1}/my/consents/${id}`),
  revokeMyConsent: (id: string) =>
    request<RevokeResponse>(`${V1}/my/consents/${id}/revoke`, {
      method: "POST",
      body: JSON.stringify({ originated_by: "subject" }),
    }),

  // ── Consent request (originate / redirect flow) ────────────────────
  getConsentRequest: (id: string) => request<ConsentRequest>(`${V1}/consent-requests/${id}`),
  // The subject authenticates by presenting their IdP id_token, then approves
  // with the scopes they agree to share.
  authenticateConsentRequest: (id: string, idToken: string) =>
    request<{ token_validated: boolean }>(`${V1}/consent-requests/${id}/authenticate`, {
      method: "POST",
      body: JSON.stringify({ id_token: idToken }),
    }),
  approveConsentRequest: (id: string, grantedScopes: string[]) =>
    request<Artefact>(`${V1}/consent-requests/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ granted_scopes: grantedScopes }),
    }),
  denyConsentRequest: (id: string, reason?: string) =>
    request<ConsentRequest>(`${V1}/consent-requests/${id}/deny`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    }),
};
