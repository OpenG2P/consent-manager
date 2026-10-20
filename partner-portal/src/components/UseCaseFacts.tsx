import type { UseCaseAccess } from "../api/types";

// A use case granted to the partner, with its purpose and data per registry.
export function UseCaseFacts({ u }: { u: UseCaseAccess }) {
  return (
    <dl className="facts">
      <dt>Purpose</dt>
      <dd>{u.purpose ? <code className="mono">{u.purpose}</code> : <span className="muted">—</span>}</dd>
      {u.grants.map((g) => (
        <div key={g.data_controller} style={{ display: "contents" }}>
          <dt>
            <code className="mono">{g.data_controller}</code>
          </dt>
          <dd>
            <div className="chips">
              {g.required_scopes.map((x) => (
                <span key={x} className="chip static selected" title="Required">
                  {x}
                </span>
              ))}
              {g.optional_scopes.map((x) => (
                <span key={x} className="chip static optional" title="Optional">
                  {x} (optional)
                </span>
              ))}
            </div>
          </dd>
        </div>
      ))}
    </dl>
  );
}
