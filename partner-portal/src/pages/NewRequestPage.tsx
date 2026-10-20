import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, compositeUrl } from "../api/client";
import { useAccess, useRequestSettings, useUseCases } from "../api/hooks";
import type { ConsentRequestCreate, ScopePolicy, UseCase } from "../api/types";
import { CheckboxGroup } from "../components/FormControls";
import { ErrorNotice } from "../components/Status";
import UseCaseRequestForm from "../components/UseCaseRequestForm";
import { dayEnd, dayStart, today } from "../format";

// The ID types a partner user can enter in Phase 1; types allowed by the
// partner's policies are added to these.
const BASE_ID_TYPES = ["FAYDA_FAN", "FARMER_ID"];

// Scopes per registry, prefilled from a use case: required + optional.
function scopesFromUseCase(u: UseCase): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const [controller, s] of Object.entries(u.consent_scopes ?? {})) {
    out[controller] = [...new Set([...(s.required ?? []), ...(s.optional ?? [])])];
  }
  return out;
}

// At the Exchange (consent_by "use_case") a request names a granted use case;
// elsewhere it names registries and data within the scope policies.
export default function NewRequestPage() {
  const settings = useRequestSettings();
  if (settings.isLoading) return <div className="loading">Loading…</div>;
  if (settings.error) return <ErrorNotice error={settings.error} what="the request settings" />;
  if (settings.data?.consent_by === "use_case") return <UseCaseRequestForm />;
  return <ScopeRequestForm />;
}

function ScopeRequestForm() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const useCaseRef = params.get("use_case") ?? "";

  const access = useAccess();
  const useCases = useUseCases(!!useCaseRef && !!compositeUrl());
  const useCase = useCases.data?.find((u) => u.use_case === useCaseRef);

  const [idType, setIdType] = useState("FAYDA_FAN");
  const [idValue, setIdValue] = useState("");
  // Other identifiers the CM requires (e.g. FARMER_ID in Agri Stack).
  const settings = useRequestSettings();
  const requiredIds = (settings.data?.required_subject_identifiers ?? []).filter((t) => t !== idType);
  const [extraIds, setExtraIds] = useState<Record<string, string>>({});
  const [purpose, setPurpose] = useState("");
  const [scopes, setScopes] = useState<Record<string, string[]>>({});
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [useCaseLabel, setUseCaseLabel] = useState(useCaseRef);
  const [prefilledFrom, setPrefilledFrom] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  // Prefill once from the use case: grants = required + optional scopes per
  // registry, purpose = the use case's purpose, use_case = its ref.
  useEffect(() => {
    if (!useCase || prefilledFrom === useCase.use_case) return;
    setScopes(scopesFromUseCase(useCase));
    if (useCase.purpose) setPurpose(useCase.purpose);
    setUseCaseLabel(useCase.use_case);
    const idTypes = useCase.input?.subject?.id_types ?? [];
    if (idTypes.length) setIdType(idTypes[0]);
    setPrefilledFrom(useCase.use_case);
  }, [useCase, prefilledFrom]);

  const list: ScopePolicy[] = useMemo(() => access.data?.scope_policies ?? [], [access.data]);
  const byController = useMemo(
    () => Object.fromEntries(list.map((b) => [b.data_controller, b])),
    [list]
  );
  const selected = Object.entries(scopes)
    .filter(([, s]) => s.length > 0)
    .map(([c]) => c);
  // Registries the use case needs that this partner has no policy for.
  const unbound = Object.keys(scopes).filter((c) => !byController[c] && scopes[c].length > 0);

  const idTypeOptions = useMemo(() => {
    const s = new Set(BASE_ID_TYPES);
    list.forEach((b) => b.allowed_subject_id_types.forEach((t) => s.add(t)));
    s.add(idType);
    return [...s];
  }, [list, idType]);

  const purposeOptions = useMemo(() => {
    const from = selected.length ? selected.map((c) => byController[c]).filter(Boolean) : list;
    const s = new Set<string>();
    from.forEach((b) => b.allowed_purposes.forEach((p) => s.add(p)));
    if (purpose) s.add(purpose);
    return [...s].sort();
  }, [selected, byController, list, purpose]);

  // ── Validation (the API checks again against the policies) ──────────
  const problems: string[] = [];
  if (!idValue.trim()) problems.push("Enter the subject's ID.");
  for (const t of requiredIds) if (!(extraIds[t] ?? "").trim()) problems.push(`Enter the subject's ${t}.`);
  if (!purpose) problems.push("Choose a purpose.");
  if (selected.length === 0) problems.push("Choose the data to request from at least one registry.");
  if (unbound.length)
    problems.push(`Your organisation has no policy for: ${unbound.join(", ")}. Remove those registries.`);
  for (const c of selected) {
    const b = byController[c];
    if (!b) continue;
    const bad = scopes[c].filter((s) => !b.allowed_data_scopes.includes(s));
    if (bad.length) problems.push(`${c}: you may not ask for ${bad.join(", ")} — untick them.`);
    if (purpose && !b.allowed_purposes.includes(purpose))
      problems.push(`${c}: purpose "${purpose}" is not allowed for this registry.`);
    if (b.allowed_subject_id_types.length && !b.allowed_subject_id_types.includes(idType))
      problems.push(`${c}: subject ID type ${idType} is not accepted by this registry.`);
  }
  if (validFrom && validUntil && validUntil < validFrom)
    problems.push("“Valid until” must be on or after “Valid from”.");
  if (validUntil && validUntil < today()) problems.push("“Valid until” is in the past.");

  const create = useMutation({
    mutationFn: () => {
      const body: ConsentRequestCreate = {
        subject_id: { type: idType, value: idValue.trim() },
        subject_identifiers: requiredIds.map((t) => ({ type: t, value: (extraIds[t] ?? "").trim() })),
        purpose: { code: purpose },
        grants: selected.map((c) => ({ data_controller: c, data_scopes: scopes[c] })),
      };
      if (validFrom || validUntil) {
        body.validity = {};
        if (validFrom) body.validity.valid_from = dayStart(validFrom);
        if (validUntil) body.validity.valid_until = dayEnd(validUntil);
      }
      if (useCaseLabel.trim()) body.use_case = useCaseLabel.trim();
      return api.createRequest(body);
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["requests"] });
      navigate(`/requests/${r.id}`);
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (problems.length === 0) create.mutate();
  };

  return (
    <div>
      <div className="spread">
        <h1 style={{ margin: 0 }}>New consent request</h1>
        <Link to="/requests" className="btn-secondary">
          Back to requests
        </Link>
      </div>
      <p className="muted page-intro">
        Raise a request while the subject is with you. Next, upload the consent form the subject
        signed and submit the request for verification.
      </p>

      {useCaseRef && useCases.isLoading && <div className="loading">Loading the use case…</div>}
      {useCaseRef && useCases.error && <ErrorNotice error={useCases.error} what="the use case" />}
      {useCaseRef && useCases.data && !useCase && (
        <div className="notice notice-error">
          Use case <code className="mono">{useCaseRef}</code> is not published.
        </div>
      )}
      {useCase && (
        <div className="notice notice-info">
          Prefilled from use case <strong>{useCase.title || useCase.name}</strong> (
          <code className="mono">{useCase.use_case}</code>): all its required and optional data.
          Untick optional data the subject does not agree to share.
        </div>
      )}

      {access.isLoading && <div className="loading">Loading your policies…</div>}
      {access.error && <ErrorNotice error={access.error} what="your policies" />}
      {access.data && list.length === 0 && (
        <div className="card">
          Your organisation has no active data-share policy, so it cannot request consent yet.
        </div>
      )}

      {access.data && list.length > 0 && (
        <form onSubmit={onSubmit}>
          <div className="card">
            <h3 className="card-title">Subject</h3>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="id-type">ID type</label>
                <select id="id-type" value={idType} onChange={(e) => setIdType(e.target.value)}>
                  {idTypeOptions.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="id-value">ID number</label>
                <input
                  id="id-value"
                  type="text"
                  autoComplete="off"
                  value={idValue}
                  onChange={(e) => setIdValue(e.target.value)}
                  placeholder="As on the subject's ID"
                />
              </div>
            </div>
            {requiredIds.map((t) => (
              <div className="grid-2" key={t}>
                <div className="field">
                  <label htmlFor={`id-${t}`}>{t}</label>
                  <input
                    id={`id-${t}`}
                    type="text"
                    autoComplete="off"
                    value={extraIds[t] ?? ""}
                    onChange={(e) => setExtraIds({ ...extraIds, [t]: e.target.value })}
                    placeholder={`The subject's ${t}`}
                  />
                  <div className="hint">Required. Consent Manager staff check it in the registry before approving.</div>
                </div>
              </div>
            ))}
          </div>

          <div className="card">
            <h3 className="card-title">Purpose and data</h3>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="purpose">Purpose</label>
                <select id="purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
                  <option value="">Choose…</option>
                  {purposeOptions.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="use-case">Use case (optional)</label>
                <input
                  id="use-case"
                  type="text"
                  value={useCaseLabel}
                  onChange={(e) => setUseCaseLabel(e.target.value)}
                  placeholder="e.g. loan-profile@1"
                />
                <div className="hint">A label shown with the request; the data asked for is below.</div>
              </div>
            </div>

            {[...list.map((b) => b.data_controller), ...unbound].map((c) => {
              const b = byController[c];
              const value = scopes[c] ?? [];
              return (
                <div className="grant" key={c}>
                  <div className="grant-head">
                    Registry <code className="mono">{c}</code>
                    {b && (
                      <span className="row" style={{ gap: 8, marginLeft: "auto" }}>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => setScopes({ ...scopes, [c]: [...b.allowed_data_scopes] })}
                        >
                          All
                        </button>
                        <button
                          type="button"
                          className="btn-secondary"
                          onClick={() => setScopes({ ...scopes, [c]: [] })}
                        >
                          None
                        </button>
                      </span>
                    )}
                  </div>
                  {b ? (
                    <CheckboxGroup
                      label="Data to request"
                      options={b.allowed_data_scopes}
                      value={value}
                      onChange={(next) => setScopes({ ...scopes, [c]: next })}
                      hint={value.length === 0 ? "Nothing ticked: no data from this registry." : undefined}
                    />
                  ) : (
                    <div className="notice notice-error">
                      Your organisation has no policy for this registry.{" "}
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => setScopes({ ...scopes, [c]: [] })}
                      >
                        Remove
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="card">
            <h3 className="card-title">Validity</h3>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="valid-from">Valid from (optional)</label>
                <input
                  id="valid-from"
                  type="date"
                  value={validFrom}
                  onChange={(e) => setValidFrom(e.target.value)}
                />
                <div className="hint">Empty: from approval.</div>
              </div>
              <div className="field">
                <label htmlFor="valid-until">Valid until (optional)</label>
                <input
                  id="valid-until"
                  type="date"
                  min={validFrom || today()}
                  value={validUntil}
                  onChange={(e) => setValidUntil(e.target.value)}
                />
                <div className="hint">Empty: the default validity under your policy.</div>
              </div>
            </div>
          </div>

          {touched && problems.length > 0 && (
            <div className="notice notice-error">
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          {create.error && (
            <div className="notice notice-error">
              {create.error instanceof ApiError ? create.error.message : "Could not create the request."}
            </div>
          )}

          <div className="actions">
            <Link to="/requests" className="btn-secondary">
              Cancel
            </Link>
            <button type="submit" className="btn-primary" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create request"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
