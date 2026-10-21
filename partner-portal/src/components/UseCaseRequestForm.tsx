import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useAccess, useRequestSettings } from "../api/hooks";
import type { ConsentRequestCreate } from "../api/types";
import { dayEnd, dayStart, today } from "../format";
import { ErrorNotice } from "./Status";
import { UseCaseFacts } from "./UseCaseFacts";

const BASE_ID_TYPES = ["FAYDA_FAN", "FARMER_ID"];

// New request at the Exchange: the partner picks one of its use cases (one
// policy per use case in Partner Management). The purpose and the data per
// registry are the use case's (shown read-only); the Consent Manager checks the
// grant again and takes them from the Composite.
export default function UseCaseRequestForm() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const access = useAccess();
  const settings = useRequestSettings();

  const useCases = useMemo(
    () => (access.data?.use_cases ?? []).filter((u) => u.available),
    [access.data]
  );
  const [ref, setRef] = useState(params.get("use_case") ?? "");
  const useCase = useCases.find((u) => u.use_case === ref);

  const [idType, setIdType] = useState("FAYDA_FAN");
  const [idValue, setIdValue] = useState("");
  const requiredIds = (settings.data?.required_subject_identifiers ?? []).filter((t) => t !== idType);
  const [extraIds, setExtraIds] = useState<Record<string, string>>({});
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [touched, setTouched] = useState(false);

  // One granted use case: choose it.
  useEffect(() => {
    if (!ref && useCases.length === 1) setRef(useCases[0].use_case);
  }, [ref, useCases]);

  // ID types: those the use case's policy accepts, else those the use case takes.
  const idTypeOptions = useMemo(() => {
    const allowed = useCase?.allowed_subject_id_types ?? [];
    const takes = useCase?.subject_id_types ?? [];
    const s = new Set(allowed.length ? allowed : takes.length ? takes : BASE_ID_TYPES);
    s.add(idType);
    return [...s];
  }, [useCase, idType]);

  useEffect(() => {
    const allowed = useCase?.allowed_subject_id_types ?? [];
    if (allowed.length && !allowed.includes(idType)) setIdType(allowed[0]);
  }, [useCase, idType]);

  const problems: string[] = [];
  if (!useCase) problems.push("Choose a use case.");
  if (!idValue.trim()) problems.push("Enter the subject's ID.");
  for (const t of requiredIds) if (!(extraIds[t] ?? "").trim()) problems.push(`Enter the subject's ${t}.`);
  const allowedTypes = useCase?.allowed_subject_id_types ?? [];
  if (allowedTypes.length && !allowedTypes.includes(idType))
    problems.push(`Subject ID type ${idType} is not accepted for this use case.`);
  if (validFrom && validUntil && validUntil < validFrom)
    problems.push("“Valid until” must be on or after “Valid from”.");
  if (validUntil && validUntil < today()) problems.push("“Valid until” is in the past.");

  const create = useMutation({
    mutationFn: () => {
      const body: ConsentRequestCreate = {
        subject_id: { type: idType, value: idValue.trim() },
        subject_identifiers: requiredIds.map((t) => ({ type: t, value: (extraIds[t] ?? "").trim() })),
        use_case: ref,
      };
      if (validFrom || validUntil) {
        body.validity = {};
        if (validFrom) body.validity.valid_from = dayStart(validFrom);
        if (validUntil) body.validity.valid_until = dayEnd(validUntil);
      }
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

  const unknownRef = !!ref && !!access.data && !useCase;

  return (
    <div>
      <div className="spread">
        <h1 style={{ margin: 0 }}>New consent request</h1>
        <Link to="/requests" className="btn-secondary">
          Back to requests
        </Link>
      </div>
      <p className="muted page-intro">
        Raise a request while the subject is with you, for one of the use cases your organisation is
        granted: the subject consents to share the data that use case needs, for its purpose. Next,
        upload the consent form the subject signed and submit the request for verification.
      </p>

      {access.isLoading && <div className="loading">Loading your use cases…</div>}
      {access.error && <ErrorNotice error={access.error} what="your use cases" />}
      {access.data && useCases.length === 0 && (
        <div className="card">
          Your organisation is granted no use case that can be asked for now, so it cannot request
          consent yet. See “What we can ask for”.
        </div>
      )}

      {access.data && useCases.length > 0 && (
        <form onSubmit={onSubmit}>
          <div className="card">
            <h3 className="card-title">Use case</h3>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="use-case">Use case</label>
                <select id="use-case" value={useCase ? ref : ""} onChange={(e) => setRef(e.target.value)}>
                  <option value="">Choose…</option>
                  {useCases.map((u) => (
                    <option key={u.use_case} value={u.use_case}>
                      {u.title ? `${u.title} (${u.use_case})` : u.use_case}
                    </option>
                  ))}
                </select>
                {unknownRef && (
                  <div className="hint">
                    <code className="mono">{ref}</code> is not granted to your organisation.
                  </div>
                )}
              </div>
            </div>
            {useCase && (
              <>
                {useCase.description && <p style={{ marginTop: 0 }}>{useCase.description}</p>}
                <UseCaseFacts u={useCase} />
                <div className="hint">
                  The consent covers this purpose and data (required, and optional data when the
                  subject agrees) and nothing else.
                </div>
              </>
            )}
          </div>

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
            <h3 className="card-title">Validity</h3>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="valid-from">Valid from (optional)</label>
                <input id="valid-from" type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
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
                <div className="hint">
                  Empty: the default validity
                  {useCase?.max_validity_duration ? ` (at most ${useCase.max_validity_duration})` : ""}.
                </div>
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
