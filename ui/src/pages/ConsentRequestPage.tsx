import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { getToken } from "../auth";
import { purposeLabel } from "./MyConsentsPage";
import "./ConsentRequestPage.css";

// First-party consent-giving screen. A partner (e.g. a bank) redirects the
// beneficiary here; the beneficiary authenticates against the registry's IdP
// and either grants or denies. The partner never sees credentials, and the
// government never approves a citizen's personal consent — this is the
// subject's own decision.
export default function ConsentRequestPage() {
  const { requestId = "" } = useParams();
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["consent-request", requestId],
    queryFn: () => api.getConsentRequest(requestId),
  });

  // Grant = authenticate the subject (present their IdP token) then approve with
  // the scopes requested. Decline = deny. The partner never sees credentials and
  // no government approval sits in this path — it is the subject's own decision.
  const approve = useMutation({
    mutationFn: async () => {
      if (!data) return;
      await api.authenticateConsentRequest(requestId, getToken());
      await api.approveConsentRequest(requestId, data.requested_scopes);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["consent-request", requestId] }),
  });
  const deny = useMutation({
    mutationFn: () => api.denyConsentRequest(requestId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["consent-request", requestId] }),
  });

  return (
    <div className="consent-screen">
      <div className="consent-card">
        <header className="consent-head">
          <img src="/openg2p-logo.svg" alt="OpenG2P" className="consent-logo" />
          <span>Consent Manager</span>
        </header>

        {isLoading && <p className="loading">Loading request…</p>}
        {error && <div className="notice notice-error">This consent request is invalid or has expired.</div>}

        {data && (data.status === "approved" || data.status === "denied") && (
          <div className={`consent-result ${data.status}`}>
            <div className="consent-result-icon">{data.status === "approved" ? "✓" : "✕"}</div>
            <h2>{data.status === "approved" ? "Consent granted" : "Consent declined"}</h2>
            <p className="muted">
              You may now return to <strong>{data.partner_id}</strong>.
            </p>
          </div>
        )}

        {data && data.status !== "approved" && data.status !== "denied" && (
          <>
            <h1>Share your data?</h1>
            <p className="lead">
              <strong>{data.partner_id}</strong> is requesting access to your registry data for
              the purpose of <strong>{purposeLabel(data.purpose)}</strong>.
            </p>

            <div className="consent-section">
              <span className="consent-label">They will be able to access</span>
              <ul className="scope-list">
                {data.requested_scopes.map((s) => (
                  <li key={s}>{humaniseScope(s)}</li>
                ))}
              </ul>
            </div>

            {data.valid_until && (
              <div className="consent-section">
                <span className="consent-label">Valid until</span>
                <div>{new Date(data.valid_until).toLocaleString()}</div>
              </div>
            )}

            <p className="consent-fineprint">
              By granting, you allow this sharing under the stated purpose only. You can withdraw
              at any time from your consent dashboard. A signed receipt will be issued for your
              records.
            </p>

            {(approve.error || deny.error) && (
              <div className="notice notice-error">Something went wrong. Please try again.</div>
            )}

            <div className="consent-actions">
              <button
                className="btn-danger"
                onClick={() => deny.mutate()}
                disabled={approve.isPending || deny.isPending}
              >
                Decline
              </button>
              <button
                className="btn-primary consent-grant"
                onClick={() => approve.mutate()}
                disabled={approve.isPending || deny.isPending}
              >
                {approve.isPending ? "Granting…" : "Grant consent"}
              </button>
            </div>
          </>
        )}
      </div>

      <p className="consent-foot muted">Secured by OpenG2P Consent Manager</p>
    </div>
  );
}

// Turn "farmer_profile.landholding" into "Farmer profile · landholding".
function humaniseScope(scope: string): string {
  return scope
    .split(".")
    .map((part) => part.replace(/_/g, " "))
    .map((part, i) => (i === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(" · ");
}
