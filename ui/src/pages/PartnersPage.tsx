import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Partner } from "../api/types";

function StatusBadge({ partner }: { partner: Partner }) {
  // Show approval state when onboarding is still in review, else lifecycle state.
  const approval = partner.approval_status;
  if (approval === "pending") return <span className="badge badge-pending">In review</span>;
  if (approval === "rejected") return <span className="badge badge-rejected">Rejected</span>;
  return <span className={`badge badge-${partner.status}`}>{partner.status}</span>;
}

export default function PartnersPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["partners"],
    queryFn: api.listPartners,
  });

  return (
    <div>
      <div className="spread">
        <h1>Partners</h1>
        <Link to="/partners/new" className="btn-primary">
          Onboard partner
        </Link>
      </div>

      <p className="muted" style={{ marginTop: -8, marginBottom: 24 }}>
        Registered data consumers. Each partner is bound to a signing key, an audience, and a
        policy that constrains what data they may ever receive.
      </p>

      {isLoading && <div className="loading">Loading partners…</div>}
      {error && <div className="notice notice-error">Could not load partners.</div>}

      {data && data.length === 0 && (
        <div className="card">
          No partners yet. <Link to="/partners/new">Onboard your first partner</Link> to begin.
        </div>
      )}

      {data && data.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Name</th>
              <th>Organisation</th>
              <th>Controller</th>
              <th>Audience</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.id}>
                <td>
                  <Link to={`/partners/${p.id}`}>{p.name}</Link>
                </td>
                <td>{p.org_name}</td>
                <td>
                  <code className="mono">{p.controller_id}</code>
                </td>
                <td>
                  <code className="mono">{p.audience}</code>
                </td>
                <td>
                  <StatusBadge partner={p} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
