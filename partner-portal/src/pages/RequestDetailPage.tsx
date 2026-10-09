import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { ConsentRequest, Evidence } from "../api/types";
import { ErrorNotice, StatusBadge } from "../components/Status";
import {
  formatBytes,
  formatDate,
  formatDateTime,
  openBlobIn,
  purposeLabel,
  saveBlob,
} from "../format";

// Same limits as the API (CONSENT_MANAGER_EVIDENCE_MAX_BYTES default, allowed types).
const MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png"];
const ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

const KIND_LABEL: Record<string, string> = {
  signed_form: "Signed consent form",
  other: "Other document",
};

function errText(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

export default function RequestDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { data: r, isLoading, error } = useQuery({
    queryKey: ["request", id],
    queryFn: () => api.getRequest(id),
  });

  const refresh = (next?: ConsentRequest) => {
    if (next) qc.setQueryData(["request", id], (old: ConsentRequest | undefined) => ({ ...old, ...next }));
    qc.invalidateQueries({ queryKey: ["request", id] });
    qc.invalidateQueries({ queryKey: ["requests"] });
  };

  const [confirmCancel, setConfirmCancel] = useState(false);
  const submit = useMutation({ mutationFn: () => api.submitRequest(id), onSuccess: refresh });
  const cancel = useMutation({
    mutationFn: () => api.cancelRequest(id),
    onSuccess: (next) => {
      setConfirmCancel(false);
      refresh(next);
    },
  });

  if (isLoading) return <div className="loading">Loading…</div>;
  if (error instanceof ApiError && error.status === 404)
    return (
      <div className="card">
        Request not found. <Link to="/requests">Back to requests</Link>
      </div>
    );
  if (error || !r) return <ErrorNotice error={error} what="the request" />;

  const evidence = r.evidence ?? [];
  const hasSignedForm = evidence.some((e) => e.kind === "signed_form");
  const pending = r.status === "pending";
  const cancellable = r.status === "pending" || r.status === "pending_verification";

  return (
    <div>
      <div className="spread">
        <div>
          <h1 style={{ margin: 0 }}>Consent request</h1>
          <div className="muted">
            <code className="mono">{r.id}</code>
          </div>
        </div>
        <div className="row">
          <StatusBadge status={r.status} />
          <Link to="/requests" className="btn-secondary">
            Back to requests
          </Link>
        </div>
      </div>

      {r.status === "approved" && r.consent_id && (
        <div className="notice notice-info">
          Approved. The consent is active:{" "}
          <Link to={`/consents/${encodeURIComponent(r.consent_id)}`}>
            <code className="mono">{r.consent_id}</code>
          </Link>
          . Present this consent ID in your queries.
        </div>
      )}
      {r.status === "rejected" && (
        <div className="notice notice-error">
          Rejected by the Consent Manager staff
          {r.verification_note ? `: ${r.verification_note}` : "."}
        </div>
      )}

      <div className="grid-2">
        <div className="card">
          <h3 className="card-title">Request</h3>
          <dl className="facts">
            <dt>Subject</dt>
            <dd>
              <code className="mono">{r.subject_id?.type}</code> {r.subject_id?.value}
            </dd>
            <dt>Purpose</dt>
            <dd>{purposeLabel(r.purpose)}</dd>
            {r.use_case && (
              <>
                <dt>Use case</dt>
                <dd>
                  <code className="mono">{r.use_case}</code>
                </dd>
              </>
            )}
            <dt>Method</dt>
            <dd>{r.method === "assisted" ? "Assisted (in person)" : (r.method ?? "—")}</dd>
            <dt>Valid from</dt>
            <dd>{r.valid_from ? formatDate(r.valid_from) : "On approval"}</dd>
            <dt>Valid until</dt>
            <dd>{formatDate(r.valid_until)}</dd>
          </dl>
        </div>
        <div className="card">
          <h3 className="card-title">Progress</h3>
          <Timeline r={r} hasSignedForm={hasSignedForm} />
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">Data requested</h3>
        {r.grants.map((g) => (
          <div className="grant" key={g.data_controller}>
            <div className="grant-head">
              Registry <code className="mono">{g.data_controller}</code>
            </div>
            <div className="chips">
              {g.data_scopes.map((s) => (
                <span key={s} className="chip static selected">
                  {s}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>

      <EvidenceCard requestId={r.id} evidence={evidence} editable={pending} onChange={refresh} />

      {(pending || cancellable) && (
        <div className="card">
          {pending && (
            <p style={{ marginTop: 0 }}>
              {hasSignedForm
                ? "When all documents are uploaded, submit the request. Consent Manager staff check the signed form against the subject and the request; the consent is active once they verify it."
                : "Upload the consent form the subject signed before you submit the request for verification."}
            </p>
          )}
          {r.status === "pending_verification" && (
            <p style={{ marginTop: 0 }}>Waiting for the Consent Manager staff to verify the signed form.</p>
          )}
          {submit.error && <div className="notice notice-error">{errText(submit.error, "Could not submit.")}</div>}
          {cancel.error && <div className="notice notice-error">{errText(cancel.error, "Could not cancel.")}</div>}
          {confirmCancel ? (
            <div className="confirm">
              <p style={{ marginTop: 0 }}>Cancel this request? This cannot be undone.</p>
              <div className="actions">
                <button className="btn-secondary" onClick={() => setConfirmCancel(false)}>
                  Keep the request
                </button>
                <button className="btn-danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                  {cancel.isPending ? "Cancelling…" : "Cancel the request"}
                </button>
              </div>
            </div>
          ) : (
            <div className="actions">
              {cancellable && (
                <button className="btn-danger" onClick={() => setConfirmCancel(true)}>
                  Cancel request
                </button>
              )}
              {pending && (
                <button
                  className="btn-primary"
                  disabled={!hasSignedForm || submit.isPending}
                  title={hasSignedForm ? undefined : "Upload the signed consent form first"}
                  onClick={() => submit.mutate()}
                >
                  {submit.isPending ? "Submitting…" : "Submit for verification"}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

type Step = { label: string; when?: string | null; detail?: string; state: "done" | "current" | "bad" | "todo" };

function Timeline({ r, hasSignedForm }: { r: ConsentRequest; hasSignedForm: boolean }) {
  const steps: Step[] = [
    {
      label: "Request created",
      when: r.created_at,
      detail: r.created_by ? `by ${r.created_by}` : undefined,
      state: "done",
    },
  ];
  const s = r.status;
  if (s === "pending") {
    steps.push({
      label: hasSignedForm ? "Signed form uploaded" : "Upload the signed form",
      state: hasSignedForm ? "done" : "current",
    });
    steps.push({ label: "Submit for verification", state: hasSignedForm ? "current" : "todo" });
    steps.push({ label: "Verification by Consent Manager staff", state: "todo" });
  } else {
    if (r.submitted_at) steps.push({ label: "Submitted for verification", when: r.submitted_at, state: "done" });
    if (s === "pending_verification") {
      steps.push({ label: "Verification by Consent Manager staff", state: "current" });
    } else if (s === "approved") {
      steps.push({
        label: "Verified — consent active",
        when: r.verified_at,
        detail: [r.verified_by && `by ${r.verified_by}`, r.verification_note].filter(Boolean).join(" · "),
        state: "done",
      });
    } else if (s === "rejected") {
      steps.push({
        label: "Rejected",
        when: r.verified_at,
        detail: [r.verified_by && `by ${r.verified_by}`, r.verification_note].filter(Boolean).join(" · "),
        state: "bad",
      });
    } else {
      steps.push({ label: s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " "), state: "bad" });
    }
  }
  return (
    <ul className="timeline">
      {steps.map((st, i) => (
        <li key={i} className={st.state}>
          <div style={{ fontWeight: st.state === "current" ? 500 : 400 }}>{st.label}</div>
          {(st.when || st.detail) && (
            <div className="when">
              {st.when ? formatDateTime(st.when) : ""}
              {st.when && st.detail ? " · " : ""}
              {st.detail}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function EvidenceCard({
  requestId,
  evidence,
  editable,
  onChange,
}: {
  requestId: string;
  evidence: Evidence[];
  editable: boolean;
  onChange: () => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("signed_form");
  const [localError, setLocalError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () => api.uploadEvidence(requestId, file!, kind),
    onSuccess: () => {
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onChange();
    },
  });
  const remove = useMutation({
    mutationFn: (evidenceId: string) => api.deleteEvidence(requestId, evidenceId),
    onSuccess: () => {
      setConfirmDelete(null);
      onChange();
    },
  });

  const pick = (f: File | null) => {
    setLocalError(null);
    upload.reset();
    if (f && !ALLOWED_TYPES.includes(f.type)) {
      setLocalError("Only PDF, JPEG or PNG files can be uploaded.");
      f = null;
    } else if (f && f.size > MAX_BYTES) {
      setLocalError(`The file is ${formatBytes(f.size)}; the limit is ${formatBytes(MAX_BYTES)}.`);
      f = null;
    }
    if (!f && fileRef.current) fileRef.current.value = "";
    setFile(f);
  };

  const fetchFile = async (e: Evidence, mode: "view" | "download") => {
    setFileError(null);
    // Open the tab now (in the click) so popup blockers allow it.
    const win = mode === "view" ? window.open("", "_blank") : null;
    try {
      const { blob, filename } = await api.downloadEvidence(requestId, e.id);
      if (mode === "view") openBlobIn(win, blob);
      else saveBlob(blob, filename ?? e.filename);
    } catch (err) {
      win?.close();
      setFileError(errText(err, "Could not fetch the file."));
    }
  };

  return (
    <div className="card">
      <h3 className="card-title">Evidence</h3>
      {evidence.length === 0 ? (
        <p className="muted" style={{ marginTop: 0 }}>No documents uploaded yet.</p>
      ) : (
        <table className="data" style={{ marginBottom: 16, boxShadow: "none" }}>
          <thead>
            <tr>
              <th>Document</th>
              <th>Size</th>
              <th>Uploaded</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {evidence.map((e) => (
              <tr key={e.id}>
                <td>
                  <div>{e.filename}</div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {KIND_LABEL[e.kind] ?? e.kind} ·{" "}
                    <span title={`SHA-256 ${e.sha256}`}>sha256 {e.sha256?.slice(0, 12)}…</span>
                  </div>
                </td>
                <td className="muted">{formatBytes(e.size_bytes)}</td>
                <td className="muted">
                  {formatDateTime(e.uploaded_at)}
                  {e.uploaded_by && <div style={{ fontSize: 12 }}>by {e.uploaded_by}</div>}
                </td>
                <td>
                  {confirmDelete === e.id ? (
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <span className="muted">Delete?</span>
                      <button className="btn-secondary" onClick={() => setConfirmDelete(null)}>
                        No
                      </button>
                      <button
                        className="btn-danger"
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(e.id)}
                      >
                        Yes, delete
                      </button>
                    </div>
                  ) : (
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="btn-secondary" onClick={() => fetchFile(e, "view")}>
                        View
                      </button>
                      <button className="btn-secondary" onClick={() => fetchFile(e, "download")}>
                        Download
                      </button>
                      {editable && (
                        <button className="btn-danger" onClick={() => setConfirmDelete(e.id)}>
                          Delete
                        </button>
                      )}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {fileError && <div className="notice notice-error">{fileError}</div>}
      {remove.error && <div className="notice notice-error">{errText(remove.error, "Could not delete.")}</div>}

      {editable && (
        <div className="confirm">
          <div className="grid-2">
            <div className="field" style={{ marginBottom: 8 }}>
              <label htmlFor="evidence-file">Upload a document</label>
              <input
                id="evidence-file"
                ref={fileRef}
                className="file-input"
                type="file"
                accept={ACCEPT}
                onChange={(e) => pick(e.target.files?.[0] ?? null)}
              />
              <div className="hint">PDF, JPEG or PNG, up to {formatBytes(MAX_BYTES)}.</div>
            </div>
            <div className="field" style={{ marginBottom: 8 }}>
              <label htmlFor="evidence-kind">Kind</label>
              <select id="evidence-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="signed_form">{KIND_LABEL.signed_form}</option>
                <option value="other">{KIND_LABEL.other}</option>
              </select>
            </div>
          </div>
          {localError && <div className="notice notice-error">{localError}</div>}
          {upload.error && <div className="notice notice-error">{errText(upload.error, "Upload failed.")}</div>}
          <div className="actions">
            <button className="btn-primary" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>
              {upload.isPending ? "Uploading…" : "Upload"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
