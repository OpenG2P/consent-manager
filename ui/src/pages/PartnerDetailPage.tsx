import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { PolicyUpsert } from "../api/types";

export default function PartnerDetailPage() {
  const { id = "" } = useParams();

  const partner = useQuery({ queryKey: ["partner", id], queryFn: () => api.getPartner(id) });

  if (partner.isLoading) return <div className="loading">Loading…</div>;
  if (partner.error || !partner.data)
    return <div className="notice notice-error">Partner not found.</div>;

  const p = partner.data;

  return (
    <div>
      <div className="spread">
        <div>
          <Link to="/partners" className="muted">
            ← Partners
          </Link>
          <h1 style={{ marginTop: 8 }}>{p.name}</h1>
        </div>
        <span className={`badge badge-${p.status}`}>{p.status}</span>
      </div>

      <ApprovalCard partnerId={id} />

      <div className="card">
        <h3 className="card-title">Details</h3>
        <table className="data">
          <tbody>
            <tr>
              <th style={{ width: 200 }}>Organisation</th>
              <td>{p.org_name}</td>
            </tr>
            <tr>
              <th>Controller</th>
              <td>
                <code className="mono">{p.controller_id}</code>
              </td>
            </tr>
            <tr>
              <th>Audience</th>
              <td>
                <code className="mono">{p.audience}</code>
              </td>
            </tr>
            <tr>
              <th>Partner Management ID</th>
              <td>
                {p.partner_mgmt_id ? (
                  <code className="mono">{p.partner_mgmt_id}</code>
                ) : (
                  <span className="muted">
                    — using audience (<code className="mono">{p.audience}</code>) —
                  </span>
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="notice notice-info">
        <strong>Signing keys are managed in Partner Management.</strong> The Consent Manager
        fetches this partner's public keys from PM (by its Partner Management ID) to verify
        signed consent objects. Rotate or revoke keys there.
      </div>

      <PolicyCard partnerId={id} />
    </div>
  );
}

// ── Approval status (read-only; approvals happen in the workflow engine) ──
function ApprovalCard({ partnerId }: { partnerId: string }) {
  const { data } = useQuery({ queryKey: ["partner", partnerId], queryFn: () => api.getPartner(partnerId) });
  const status = data?.approval_status;
  if (!status || status === "not_required") return null;
  const ref = data?.awe_request_id;

  const map: Record<string, { cls: string; label: string; text: string }> = {
    pending: {
      cls: "notice-info",
      label: "In review",
      text: "This partner is awaiting approval in the workflow engine. It cannot validate consents until approved.",
    },
    approved: {
      cls: "notice-info",
      label: "Approved",
      text: "Onboarding was approved. The partner is active.",
    },
    rejected: {
      cls: "notice-error",
      label: "Rejected",
      text: "The onboarding request was rejected in the workflow engine.",
    },
  };
  const m = map[status] ?? map.pending;
  return (
    <div className={`notice ${m.cls}`}>
      <strong>Approval: {m.label}.</strong> {m.text}
      {ref && (
        <>
          {" "}
          <span className="muted">AWE request: </span>
          <code className="mono">{ref}</code>
        </>
      )}
    </div>
  );
}

// ── Policy ────────────────────────────────────────────────────────────
function PolicyCard({ partnerId }: { partnerId: string }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const policy = useQuery({
    queryKey: ["policy", partnerId],
    queryFn: () => api.getPolicy(partnerId),
    retry: false,
  });

  const save = useMutation({
    mutationFn: (data: PolicyUpsert) => api.putPolicy(partnerId, data),
    onSuccess: () => {
      setEditing(false);
      qc.invalidateQueries({ queryKey: ["policy", partnerId] });
      qc.invalidateQueries({ queryKey: ["partner", partnerId] });
    },
  });

  const existing = policy.data;

  if (editing || (!existing && !policy.isLoading)) {
    return (
      <PolicyForm
        initial={existing}
        pending={save.isPending}
        error={save.error instanceof ApiError ? save.error.message : undefined}
        onCancel={existing ? () => setEditing(false) : undefined}
        onSave={(data) => save.mutate(data)}
      />
    );
  }

  return (
    <div className="card">
      <div className="spread">
        <h3 className="card-title" style={{ margin: 0 }}>
          Policy {existing?.version != null && <span className="muted">v{existing.version}</span>}
        </h3>
        {existing && (
          <button className="btn-secondary" onClick={() => setEditing(true)}>
            Edit policy
          </button>
        )}
      </div>

      {policy.isLoading && <p className="loading">Loading policy…</p>}

      {existing && (
        <table className="data">
          <tbody>
            <PolicyRow label="Allowed data scopes" values={existing.allowed_data_scopes} />
            <PolicyRow label="Allowed purposes" values={existing.allowed_purposes} />
            <PolicyRow label="Allowed subject ID types" values={existing.allowed_subject_id_types} />
            <PolicyRow label="Allowed signing algs" values={existing.allowed_signing_algs} />
            <tr>
              <th style={{ width: 220 }}>Max validity</th>
              <td>{humaniseDuration(existing.max_validity_duration)}</td>
            </tr>
            <tr>
              <th>Fetch type</th>
              <td>{existing.fetch_type}</td>
            </tr>
            {existing.fetch_type === "periodic" && (
              <tr>
                <th>Max fetch frequency</th>
                <td>{humaniseDuration(existing.max_fetch_frequency)}</td>
              </tr>
            )}
            <tr>
              <th>Data life</th>
              <td>{humaniseDuration(existing.data_life)}</td>
            </tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

function PolicyRow({ label, values }: { label: string; values: string[] }) {
  return (
    <tr>
      <th style={{ width: 220 }}>{label}</th>
      <td>
        <div className="chips">
          {values.length === 0 && <span className="muted">—</span>}
          {values.map((v) => (
            <span key={v} className="chip selected">
              {v}
            </span>
          ))}
        </div>
      </td>
    </tr>
  );
}

const DEFAULT_POLICY: PolicyUpsert = {
  allowed_data_scopes: [],
  allowed_purposes: [],
  allowed_subject_id_types: [],
  allowed_signing_algs: ["EdDSA"],
  max_validity_duration: "P30D",
  fetch_type: "oneshot",
  max_fetch_frequency: null,
  data_life: null,
};

function PolicyForm({
  initial,
  onSave,
  onCancel,
  pending,
  error,
}: {
  initial?: PolicyUpsert;
  onSave: (data: PolicyUpsert) => void;
  onCancel?: () => void;
  pending: boolean;
  error?: string;
}) {
  const [form, setForm] = useState<PolicyUpsert>(initial ?? DEFAULT_POLICY);

  const csv = (k: keyof PolicyUpsert) => (e: React.ChangeEvent<HTMLTextAreaElement>) =>
    setForm((f) => ({
      ...f,
      [k]: e.target.value
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean),
    }));

  const listVal = (v: string[]) => v.join("\n");

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(form);
      }}
    >
      <h3 className="card-title">{initial ? "Edit policy" : "Define policy"}</h3>
      <p className="muted" style={{ marginTop: -8 }}>
        The policy is the outer bound on every consent. Effective fields returned to the registry
        are always the consent's scope ∩ this policy. One entry per line (or comma-separated).
      </p>

      <div className="field">
        <label>Allowed data scopes</label>
        <textarea value={listVal(form.allowed_data_scopes)} onChange={csv("allowed_data_scopes")} placeholder="farmer_profile.basic&#10;farmer_profile.landholding" />
      </div>
      <div className="field">
        <label>Allowed purposes</label>
        <textarea value={listVal(form.allowed_purposes)} onChange={csv("allowed_purposes")} placeholder="loan_origination&#10;subsidy_verification" />
      </div>
      <div className="field">
        <label>Allowed subject ID types</label>
        <textarea value={listVal(form.allowed_subject_id_types)} onChange={csv("allowed_subject_id_types")} placeholder="national_id&#10;farmer_id" />
      </div>
      <div className="field">
        <label>Allowed signing algorithms</label>
        <textarea value={listVal(form.allowed_signing_algs)} onChange={csv("allowed_signing_algs")} placeholder="EdDSA&#10;ES256" />
      </div>

      <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
        <div className="field" style={{ flex: 1 }}>
          <label>Max validity</label>
          <input
            type="text"
            value={form.max_validity_duration ?? ""}
            onChange={(e) =>
              setForm((f) => ({ ...f, max_validity_duration: e.target.value.trim() || null }))
            }
            placeholder="P30D"
          />
          <div className="hint">
            ISO-8601 duration — {humaniseDuration(form.max_validity_duration)}
          </div>
        </div>
        <div className="field" style={{ flex: 1 }}>
          <label>Fetch type</label>
          <select
            value={form.fetch_type}
            onChange={(e) => setForm((f) => ({ ...f, fetch_type: e.target.value as PolicyUpsert["fetch_type"] }))}
          >
            <option value="oneshot">One-shot</option>
            <option value="periodic">Periodic</option>
          </select>
        </div>
      </div>

      {form.fetch_type === "periodic" && (
        <div className="row" style={{ alignItems: "flex-start", gap: 24 }}>
          <div className="field" style={{ flex: 1 }}>
            <label>Min interval between fetches</label>
            <input
              type="text"
              value={form.max_fetch_frequency ?? ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, max_fetch_frequency: e.target.value.trim() || null }))
              }
              placeholder="P1D"
            />
            <div className="hint">ISO-8601 duration — {humaniseDuration(form.max_fetch_frequency)}</div>
          </div>
          <div className="field" style={{ flex: 1 }}>
            <label>Data life</label>
            <input
              type="text"
              value={form.data_life ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, data_life: e.target.value.trim() || null }))}
              placeholder="P30D"
            />
            <div className="hint">ISO-8601 duration — {humaniseDuration(form.data_life)}</div>
          </div>
        </div>
      )}

      {error && <div className="notice notice-error">{error}</div>}

      <div className="notice notice-info">
        Saving a policy that widens access is submitted for approval before it takes effect.
      </div>

      <div className="row">
        <button type="submit" className="btn-primary" disabled={pending}>
          {pending ? "Saving…" : "Save policy"}
        </button>
        {onCancel && (
          <button type="button" className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

// Render an ISO-8601 duration (P1Y, P30D, PT12H, P1DT6H) in plain words.
function humaniseDuration(iso?: string | null): string {
  if (!iso) return "—";
  const m = /^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/.exec(
    iso.trim()
  );
  if (!m) return iso;
  const units: [string, string][] = [
    [m[1], "year"],
    [m[2], "month"],
    [m[3], "week"],
    [m[4], "day"],
    [m[5], "hour"],
    [m[6], "minute"],
    [m[7], "second"],
  ];
  const parts = units
    .filter(([v]) => v)
    .map(([v, label]) => `${v} ${label}${Number(v) > 1 ? "s" : ""}`);
  return parts.length ? parts.join(", ") : iso;
}
