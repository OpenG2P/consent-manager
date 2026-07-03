import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { PartnerCreate } from "../api/types";

const EMPTY: PartnerCreate = {
  partner_mgmt_id: "",
  audience: "",
  controller_id: "",
  name: "",
};

export default function PartnerOnboardPage() {
  const [form, setForm] = useState<PartnerCreate>(EMPTY);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const create = useMutation({
    mutationFn: () =>
      api.createPartner({
        ...form,
        partner_mgmt_id: form.partner_mgmt_id?.trim() || null,
        name: form.name?.trim() || null,
      }),
    onSuccess: (partner) => {
      qc.invalidateQueries({ queryKey: ["partners"] });
      navigate(`/partners/${partner.id}`);
    },
  });

  const set = (k: keyof PartnerCreate) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const valid = form.audience && form.controller_id;

  return (
    <div>
      <div className="spread">
        <h1>New binding</h1>
        <Link to="/partners" className="btn-secondary">
          Cancel
        </Link>
      </div>

      <div className="notice notice-info">
        A binding links a <strong>Partner-Management partner</strong> to a controller. Partner
        identity, keys and onboarding are managed in Partner Management — here you only bind that
        partner to a controller and (next) define its data-share policy.
      </div>

      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) create.mutate();
        }}
      >
        <div className="field">
          <label>Partner Management ID</label>
          <input
            type="text"
            value={form.partner_mgmt_id ?? ""}
            onChange={set("partner_mgmt_id")}
            placeholder="PARTNER_ACME"
          />
          <div className="hint">
            The partner's reference in Partner Management, used to fetch its signing keys to verify
            consent objects. Leave blank to use the audience as the reference.
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
          <label>Controller ID</label>
          <input
            type="text"
            value={form.controller_id}
            onChange={set("controller_id")}
            placeholder="farmer-registry"
          />
          <div className="hint">
            The registry (data controller) this binding is for. One Consent Manager serves several
            controllers; the same partner may be bound to more than one.
          </div>
        </div>

        <div className="field">
          <label>Label (optional)</label>
          <input type="text" value={form.name ?? ""} onChange={set("name")} placeholder="Acme Lending" />
          <div className="hint">Display label only — authoritative identity lives in Partner Management.</div>
        </div>

        {create.error && (
          <div className="notice notice-error">
            {create.error instanceof ApiError ? create.error.message : "Failed to create binding."}
          </div>
        )}

        <div className="row">
          <button type="submit" className="btn-primary" disabled={!valid || create.isPending}>
            {create.isPending ? "Creating…" : "Create binding"}
          </button>
        </div>
      </form>
    </div>
  );
}
