{{/*
Service account name for the API component.
*/}}
{{- define "consentManagerApi.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ default (include "common.names.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
{{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{/*
Render the env: list from .Values.envVars (literal/templated) and
.Values.envVarsFrom (valueFrom blocks). Inner Helm templates are resolved
against the root context ($).
*/}}
{{- define "consentManagerApi.envVars" -}}
{{- range $key, $value := .Values.envVars }}
- name: {{ $key }}
  value: {{ tpl (printf "%v" $value) $ | quote }}
{{- end }}
{{- range $key, $spec := .Values.envVarsFrom }}
- name: {{ $key }}
  valueFrom:
{{ tpl (toYaml $spec) $ | indent 4 }}
{{- end }}
{{- end -}}

{{/*
Sanity Keycloak client-credentials env (the consent-manager admin client). Used
for CM admin calls and as the fallback token for PM admin seeding when no
dedicated partner_manager client is configured.
*/}}
{{- define "consentManagerSanity.kcClientEnv" -}}
- name: SANITY_TOKEN_URL
  value: "{{ tpl .Values.global.keycloakIssuerUrl $ }}/protocol/openid-connect/token"
- name: SANITY_CLIENT_ID
  value: {{ tpl .Values.global.consentManagerAuthClientId $ | quote }}
- name: SANITY_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ tpl .Values.global.consentManagerAuthClientId $ }}
      key: client_secret
      optional: true
{{- end -}}

{{/*
Partner Management seed env — shared by the pm-seed Job (deploy-time seeding)
and the sanity Job (its idempotent safety-net check). The signing private key
is bundled in the sanity image (TEST only); PM stores the derived public half.
*/}}
{{- define "consentManagerSanity.pmSeedEnv" -}}
- name: SANITY_VERIFY_TLS
  value: {{ .Values.sanity.verifyTls | quote }}
- name: SANITY_PM_PARTNER_API_URL
  value: {{ tpl .Values.global.partnerManagementApiUrl $ | quote }}
- name: SANITY_PM_ADMIN_URL
  value: {{ tpl .Values.global.partnerManagementAdminApiUrl $ | quote }}
# Authenticate to PM's admin API AS PM's own admin client (holds partner_manager).
- name: SANITY_PM_ADMIN_TOKEN_URL
  value: "{{ tpl .Values.global.keycloakIssuerUrl $ }}/protocol/openid-connect/token"
- name: SANITY_PM_ADMIN_CLIENT_ID
  value: {{ tpl .Values.global.pmSeedClientId $ | quote }}
- name: SANITY_PM_ADMIN_CLIENT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ tpl .Values.global.pmSeedClientId $ | quote }}
      key: client_secret
      optional: true
{{- end -}}
