import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { PartnerCreate } from "../api/types";

const EMPTY: PartnerCreate = {
  name: "",
  org_name: "",
  audience: "",
  controller_id: "",
  partner_mgmt_id: "",
};

export default function PartnerOnboardPage() {
  const [form, setForm] = useState<PartnerCreate>(EMPTY);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const create = useMutation({
    mutationFn: () =>
      api.createPartner({ ...form, partner_mgmt_id: form.partner_mgmt_id?.trim() || null }),
    onSuccess: (partner) => {
      qc.invalidateQueries({ queryKey: ["partners"] });
      navigate(`/partners/${partner.id}`);
    },
  });

  const set = (k: keyof PartnerCreate) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const valid = form.name && form.org_name && form.audience && form.controller_id;

  return (
    <div>
      <div className="spread">
        <h1>Onboard partner</h1>
        <Link to="/partners" className="btn-secondary">
          Cancel
        </Link>
      </div>

      <div className="notice notice-info">
        Onboarding a partner (or later widening its policy) is submitted for approval. The
        partner stays <strong>in review</strong> until an approver signs off in the workflow
        engine; only then can its consents validate.
      </div>

      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) create.mutate();
        }}
      >
        <div className="field">
          <label>Partner name</label>
          <input type="text" value={form.name} onChange={set("name")} placeholder="Acme Lending" />
          <div className="hint">Human-readable label shown across the console.</div>
        </div>

        <div className="field">
          <label>Organisation</label>
          <input
            type="text"
            value={form.org_name}
            onChange={set("org_name")}
            placeholder="Acme Financial Services Ltd."
          />
          <div className="hint">Legal entity acting as data controller/processor.</div>
        </div>

        <div className="field">
          <label>Controller ID</label>
          <input
            type="text"
            value={form.controller_id}
            onChange={set("controller_id")}
            placeholder="farmer-registry"
          />
          <div className="hint">
            The registry (data controller) this partner is onboarded against. One Consent Manager
            can serve several controllers.
          </div>
        </div>

        <div className="field">
          <label>Audience</label>
          <input
            type="text"
            value={form.audience}
            onChange={set("audience")}
            placeholder="https://registry.example.org"
          />
          <div className="hint">
            Expected <code className="mono">aud</code> claim in the partner's signed consent
            objects. Validation rejects mismatches.
          </div>
        </div>

        <div className="field">
          <label>Partner Management ID (optional)</label>
          <input
            type="text"
            value={form.partner_mgmt_id ?? ""}
            onChange={set("partner_mgmt_id")}
            placeholder="PARTNER_ACME"
          />
          <div className="hint">
            The partner's reference in the Partner Management service. The Consent Manager fetches
            this partner's signing keys from there to verify consent objects. Leave blank to use
            the audience as the reference.
          </div>
        </div>

        {create.error && (
          <div className="notice notice-error">
            {create.error instanceof ApiError
              ? create.error.message
              : "Failed to create partner."}
          </div>
        )}

        <div className="row">
          <button type="submit" className="btn-primary" disabled={!valid || create.isPending}>
            {create.isPending ? "Submitting…" : "Create & submit for approval"}
          </button>
        </div>
      </form>
    </div>
  );
}
