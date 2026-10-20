import { Link } from "react-router-dom";
import { useAccess } from "../api/hooks";
import type { ScopePolicy, UseCaseAccess } from "../api/types";
import { ErrorNotice } from "../components/Status";
import { UseCaseFacts } from "../components/UseCaseFacts";

function Chips({ values, empty }: { values: string[]; empty: string }) {
  if (!values.length) return <span className="muted">{empty}</span>;
  return (
    <div className="chips">
      {values.map((v) => (
        <span key={v} className="chip static">
          <code className="mono">{v}</code>
        </span>
      ))}
    </div>
  );
}

function ScopePolicyCard({ b }: { b: ScopePolicy }) {
  return (
    <div className="card">
      <h3 className="card-title">
        Registry <code className="mono">{b.data_controller}</code>
      </h3>
      <dl className="facts">
        <dt>Data scopes</dt>
        <dd>
          <Chips values={b.allowed_data_scopes} empty="None" />
        </dd>
        <dt>Purposes</dt>
        <dd>
          <Chips values={b.allowed_purposes} empty="None" />
        </dd>
        <dt>Subject ID types</dt>
        <dd>
          <Chips values={b.allowed_subject_id_types} empty="Any" />
        </dd>
        <dt>Policy version</dt>
        <dd>v{b.policy_version}</dd>
      </dl>
    </div>
  );
}

function UseCaseCard({ u }: { u: UseCaseAccess }) {
  return (
    <div className="card">
      <div className="spread" style={{ alignItems: "flex-start" }}>
        <div>
          <h3 style={{ margin: 0 }}>{u.title || u.use_case}</h3>
          <div className="muted">
            <code className="mono">{u.use_case}</code> · policy v{u.policy_version}
          </div>
        </div>
        {u.available && (
          <Link to={`/requests/new?use_case=${encodeURIComponent(u.use_case)}`} className="btn-primary">
            New request for this use case
          </Link>
        )}
      </div>
      {u.description && <p style={{ marginTop: 0 }}>{u.description}</p>}
      {!u.available && <div className="notice notice-error">{u.detail || "Not available now."}</div>}
      {u.available && <UseCaseFacts u={u} />}
      {u.allowed_subject_id_types.length > 0 && (
        <div className="muted">Subject ID types accepted: {u.allowed_subject_id_types.join(", ")}</div>
      )}
    </div>
  );
}

// Read-only: what the partner may ask for. At the Exchange, the use cases its
// use-case policy grants (purpose and data per registry from the Composite);
// elsewhere its data-share policies per registry. Policies are set in Partner
// Management, not here.
export default function AccessPage() {
  const { data, isLoading, error } = useAccess();
  const byUseCase = data?.consent_by === "use_case";

  return (
    <div>
      <h1>What we can ask for</h1>
      {byUseCase ? (
        <p className="muted page-intro">
          The use cases your organisation is granted. A consent is asked for one use case: the
          subject agrees to share the data it needs from each registry, for its purpose. Grants are
          set in Partner Management; to change one, ask the Partner Management administrator.
        </p>
      ) : (
        <p className="muted page-intro">
          Your organisation's active data-share policies: per registry, the data you may ask a
          subject to share, for which purposes, and the subject IDs accepted. Policies are set in
          Partner Management; to change one, ask the Consent Manager / Partner Management
          administrator.
        </p>
      )}

      {isLoading && <div className="loading">Loading…</div>}
      {error && <ErrorNotice error={error} what="what you can ask for" />}

      {data && byUseCase && data.use_cases.length === 0 && (
        <div className="card">
          Your organisation is granted no use case yet, so it cannot request consent. Ask the
          Partner Management administrator to grant one.
        </div>
      )}
      {data && !byUseCase && data.scope_policies.length === 0 && (
        <div className="card">
          Your organisation has no active data-share policy yet, so it cannot request consent. Ask
          the Consent Manager / Partner Management administrator to set one in Partner Management.
        </div>
      )}

      {byUseCase
        ? data?.use_cases.map((u) => <UseCaseCard key={u.use_case} u={u} />)
        : data?.scope_policies.map((b) => <ScopePolicyCard key={b.data_controller} b={b} />)}
    </div>
  );
}
