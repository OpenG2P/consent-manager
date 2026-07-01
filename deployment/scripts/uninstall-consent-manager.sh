#!/usr/bin/env bash
#
# uninstall-consent-manager.sh
# ----------------------------
# Cleanly uninstall an OpenG2P Consent Manager Helm release and every resource it
# touched, including the PostgreSQL database and role that live inside the
# commons-postgresql instance (which are NOT owned by the CM Helm release and
# therefore survive `helm uninstall`).
#
# What it does, in order:
#   0. Stop in-flight Jobs (keycloak-init / postgres-init hooks, expire jobs)
#      so `helm uninstall --wait` does not block on them.
#   1. helm uninstall <release>            (API Deployment/Service/HPA/CronJob,
#                                           helm-owned Secrets & ConfigMaps, etc.)
#   2. Delete leftover Jobs + their Pods   (subchart hook Jobs keep themselves
#                                           around via hook-delete-policy:
#                                           before-hook-creation)
#   3. Sweep leftover Secrets/ConfigMaps   (label app.kubernetes.io/instance)
#   4. Drop the Postgres database + role   (via `kubectl exec` into
#                                           commons-postgresql)
#   5. Delete PVCs by label                (CM has none of its own by default,
#                                           but swept for safety)
#   6. Delete PVs still bound to those PVCs
#
# Database dropped (only the one THIS chart's postgres-init creates):
#   - <release-underscored>            e.g. consent_manager
# It does NOT drop registry_db, pbms_db, or any other module's database.
#
# Requires: kubectl (cluster admin), helm, bash 4+.
#
# USAGE:
#   ./uninstall-consent-manager.sh \
#       --namespace <ns> \
#       [--release <name>]              (default: consent-manager)
#       [--postgres-release <name>]     (default: commons-postgresql)
#       [--postgres-namespace <ns>]     (default: same as --namespace)
#       [--drop-signing-secret]         (also delete the .p12 signing Secret;
#                                        kept by default since you created it)
#       [--signing-secret <name>]       (default: consent-manager-signing)
#       [--keep-pvs]                    (delete PVCs but not PVs)
#       [--dry-run]                     (print actions, change nothing)
#       [--yes]                         (skip interactive confirmation)
#
# EXAMPLES:
#   ./uninstall-consent-manager.sh --namespace trial --dry-run
#   ./uninstall-consent-manager.sh --namespace trial
#   ./uninstall-consent-manager.sh --namespace trial --yes --drop-signing-secret

set -euo pipefail

# ---------- defaults ----------
RELEASE="consent-manager"
NAMESPACE=""
POSTGRES_RELEASE="commons-postgresql"
POSTGRES_NAMESPACE=""
SIGNING_SECRET="consent-manager-signing"
DROP_SIGNING_SECRET=false
KEEP_PVS=false
DRY_RUN=false
ASSUME_YES=false

# ---------- cli ----------
usage() { sed -n '2,52p' "$0"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release)            RELEASE="$2";            shift 2 ;;
    --namespace|-n)       NAMESPACE="$2";          shift 2 ;;
    --postgres-release)   POSTGRES_RELEASE="$2";   shift 2 ;;
    --postgres-namespace) POSTGRES_NAMESPACE="$2"; shift 2 ;;
    --signing-secret)     SIGNING_SECRET="$2";     shift 2 ;;
    --drop-signing-secret) DROP_SIGNING_SECRET=true; shift ;;
    --keep-pvs)           KEEP_PVS=true;           shift ;;
    --dry-run)            DRY_RUN=true;            shift ;;
    --yes|-y)             ASSUME_YES=true;         shift ;;
    -h|--help)            usage ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$NAMESPACE" ]] && { echo "ERROR: --namespace is required"; exit 1; }
[[ -z "$POSTGRES_NAMESPACE" ]] && POSTGRES_NAMESPACE="$NAMESPACE"

# ---------- derived DB / role names (templated exactly like values.yaml) ----------
#   consentDB:     '{{ printf "%s" .Release.Name | replace "-" "_" }}'
#   consentDBUser: '{{ printf "%s_user" .Release.Name | replace "-" "_" }}'
RELEASE_UNDERSCORED="${RELEASE//-/_}"
CONSENT_DB="${RELEASE_UNDERSCORED}"
CONSENT_USER="${RELEASE_UNDERSCORED}_user"
# postgres-init's DB password Secret (global.consentDBSecret = '<release>-db').
# Deleting it AND the role together keeps a reinstall's Secret/role passwords in
# sync — otherwise a surviving Secret + dropped role => auth failure next install.
DB_SECRET="${RELEASE}-db"

# ---------- helpers ----------
_red()   { printf "\033[31m%s\033[0m\n" "$*"; }
_green() { printf "\033[32m%s\033[0m\n" "$*"; }
_yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
_blue()  { printf "\033[34m%s\033[0m\n" "$*"; }

run() {
  # Print + execute, or just print if --dry-run. Never aborts on non-zero —
  # cleanup commands are idempotent; already-deleted resources are fine.
  echo "  \$ $*"
  if [[ "$DRY_RUN" == false ]]; then
    eval "$@" || _yellow "  (command returned non-zero — continuing)"
  fi
}

kexec_psql() {
  # Run SQL as postgres superuser inside the commons-postgresql pod, using
  # PGPASSWORD from the pod's own env. Tolerant of failure — script continues.
  local sql="$1"
  local cmd=(kubectl exec -n "$POSTGRES_NAMESPACE" "$PG_POD" -c postgresql -- \
             bash -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -U postgres -v ON_ERROR_STOP=0 -c \"$sql\"")
  echo "  \$ psql -U postgres -c \"$sql\""
  if [[ "$DRY_RUN" == false ]]; then
    "${cmd[@]}" || _yellow "  (psql returned non-zero — continuing)"
  fi
}

# ---------- pre-flight ----------
_blue "==> Pre-flight checks"
command -v kubectl >/dev/null || { _red "kubectl not found"; exit 1; }
command -v helm    >/dev/null || { _red "helm not found";    exit 1; }

if kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
  NAMESPACE_EXISTS=true
  _green "  Namespace '$NAMESPACE' exists"
else
  NAMESPACE_EXISTS=false
  _yellow "  Namespace '$NAMESPACE' does not exist — namespace-scoped cleanup will be skipped"
fi

# Locate commons-postgresql pod (Bitnami labels, then fall back to name).
PG_POD=""
if kubectl get ns "$POSTGRES_NAMESPACE" >/dev/null 2>&1; then
  PG_POD=$(kubectl get pod -n "$POSTGRES_NAMESPACE" \
    -l "app.kubernetes.io/instance=$POSTGRES_RELEASE,app.kubernetes.io/name=postgresql" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -z "$PG_POD" ]] && kubectl get pod -n "$POSTGRES_NAMESPACE" "${POSTGRES_RELEASE}-0" >/dev/null 2>&1; then
    PG_POD="${POSTGRES_RELEASE}-0"
  fi
fi
if [[ -z "$PG_POD" ]]; then
  PG_POD_FOUND=false
  _yellow "  commons-postgresql pod not found — DB / role drop step will be skipped"
else
  PG_POD_FOUND=true
  _green "  Found Postgres pod: $PG_POD (namespace: $POSTGRES_NAMESPACE)"
fi

if helm -n "$NAMESPACE" status "$RELEASE" >/dev/null 2>&1; then
  _green "  Helm release '$RELEASE' found in namespace '$NAMESPACE'"
  HELM_RELEASE_EXISTS=true
else
  _yellow "  Helm release '$RELEASE' not found — will skip helm uninstall step"
  HELM_RELEASE_EXISTS=false
fi

# ---------- plan ----------
_blue "==> Plan"
echo
echo "Will DELETE:"
echo "  - Helm release:        $RELEASE (namespace: $NAMESPACE)"
echo "  - Postgres database:   $CONSENT_DB"
echo "  - Postgres role:       $CONSENT_USER"
echo "  - namespace resources: Jobs/Secrets/ConfigMaps/PVCs/PVs labeled app.kubernetes.io/instance=$RELEASE"
[[ "$DROP_SIGNING_SECRET" == true ]] && echo "  - Signing Secret:      $SIGNING_SECRET (--drop-signing-secret)"
echo
echo "Will PRESERVE:"
echo "  - Postgres instance/pod: ${PG_POD:-<not found — DB drop skipped>} ($POSTGRES_NAMESPACE)"
echo "  - Other module databases (registry_db, pbms_db, …)"
echo "  - Keycloak realm/client 'consent-manager' (lives in Keycloak; reused on reinstall)"
[[ "$DROP_SIGNING_SECRET" == false ]] && echo "  - Signing Secret '$SIGNING_SECRET' (use --drop-signing-secret to remove)"
echo

if [[ "$NAMESPACE_EXISTS" == true ]]; then
  for kind in job secret configmap pvc; do
    echo "${kind^}s (label app.kubernetes.io/instance=$RELEASE):"
    kubectl -n "$NAMESPACE" get "$kind" -l "app.kubernetes.io/instance=$RELEASE" \
      --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"
  done
fi
echo

# ---------- confirmation ----------
if [[ "$DRY_RUN" == true ]]; then
  _yellow "DRY-RUN: no changes will be made."
fi
if [[ "$ASSUME_YES" == false && "$DRY_RUN" == false ]]; then
  _red "This is destructive. Type the release name ('$RELEASE') to confirm:"
  read -r CONFIRM
  [[ "$CONFIRM" != "$RELEASE" ]] && { _red "Confirmation did not match. Aborting."; exit 1; }
fi

# ========== STEP 0: stop in-flight Jobs ==========
_blue "==> [0/6] Stop in-flight Jobs so the uninstall doesn't hang"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete job -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found --wait=false"
  run "kubectl -n '$NAMESPACE' delete pod -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found --force --grace-period=0 --wait=false"
else
  echo "  (skipped — namespace not present)"
fi

# ========== STEP 1: helm uninstall ==========
_blue "==> [1/6] Helm uninstall"
if [[ "$HELM_RELEASE_EXISTS" == true ]]; then
  run "helm uninstall '$RELEASE' -n '$NAMESPACE' --wait --timeout 5m || true"
else
  echo "  (skipped — release not present)"
fi

# ========== STEP 2: delete leftover Jobs (and their Pods) ==========
# Subchart hook Jobs (postgres-init, keycloak-init) use hook-delete-policy:
# before-hook-creation, so helm uninstall leaves them. Delete here BEFORE the DB
# drop so their pods close Postgres connections cleanly.
_blue "==> [2/6] Delete leftover Jobs and their Pods"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete job -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found --wait=true --timeout=2m"
  run "kubectl -n '$NAMESPACE' delete pod -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found --field-selector=status.phase!=Running"
else
  echo "  (skipped — namespace not present)"
fi

# ========== STEP 3: sweep leftover Secrets & ConfigMaps ==========
_blue "==> [3/6] Sweep leftover Secrets / ConfigMaps"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete secret    -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
  run "kubectl -n '$NAMESPACE' delete configmap -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
  # Explicitly drop the DB password Secret by name (the label sweep may miss it,
  # depending on how postgres-init labels it). Must go together with the role
  # drop in step 4 so a reinstall's Secret and role passwords match.
  run "kubectl -n '$NAMESPACE' delete secret '$DB_SECRET' --ignore-not-found"
  if [[ "$DROP_SIGNING_SECRET" == true ]]; then
    run "kubectl -n '$NAMESPACE' delete secret '$SIGNING_SECRET' --ignore-not-found"
  fi
else
  echo "  (skipped — namespace not present)"
fi

# ========== STEP 4: drop Postgres DB & role ==========
_blue "==> [4/6] Drop Postgres database and role"
if [[ "$PG_POD_FOUND" == true ]]; then
  echo "  - Database: $CONSENT_DB"
  kexec_psql "REVOKE CONNECT ON DATABASE \\\"$CONSENT_DB\\\" FROM PUBLIC;"
  kexec_psql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$CONSENT_DB' AND pid <> pg_backend_pid();"
  kexec_psql "DROP DATABASE IF EXISTS \\\"$CONSENT_DB\\\";"
  echo "  - Role: $CONSENT_USER"
  kexec_psql "REASSIGN OWNED BY \\\"$CONSENT_USER\\\" TO postgres;"
  kexec_psql "DROP OWNED BY \\\"$CONSENT_USER\\\";"
  kexec_psql "DROP ROLE IF EXISTS \\\"$CONSENT_USER\\\";"
else
  echo "  (skipped — commons-postgresql pod not reachable)"
fi

# ========== STEP 5: PVCs ==========
_blue "==> [5/6] Delete PVCs"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete pvc -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
else
  echo "  (skipped — namespace not present)"
fi

# ========== STEP 6: PVs ==========
_blue "==> [6/6] Delete PVs"
if [[ "$KEEP_PVS" == true ]]; then
  _yellow "  (skipped — --keep-pvs)"
else
  pv_list=$(kubectl get pv -o json 2>/dev/null | \
    jq -r --arg ns "$NAMESPACE" \
      '.items[] | select(.spec.claimRef.namespace==$ns) | select(.status.phase=="Released" or .status.phase=="Failed") | .metadata.name' \
    2>/dev/null || true)
  pv_labeled=$(kubectl get pv -l "app.kubernetes.io/instance=$RELEASE" \
                 -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
  pv_all=$(echo "$pv_list $pv_labeled" | tr ' ' '\n' | sort -u | tr '\n' ' ' | sed 's/^ *//;s/ *$//')
  if [[ -z "$pv_all" ]]; then
    echo "  (no PVs to delete)"
  else
    for pv in $pv_all; do
      run "kubectl delete pv '$pv' --ignore-not-found"
    done
  fi
fi

echo
_green "==> Done."
[[ "$DRY_RUN" == true ]] && _yellow "    (dry-run — nothing was actually changed)"
_yellow "Note: the Keycloak realm/client 'consent-manager' is left intact — it lives"
_yellow "      in Keycloak, not in this namespace. keycloak-init is idempotent, so a"
_yellow "      reinstall reuses it (regenerating the k8s client secret as needed)."
[[ "$DROP_SIGNING_SECRET" == false ]] && \
_yellow "      The .p12 signing Secret '$SIGNING_SECRET' was kept; rerun with"
_yellow "      --drop-signing-secret to remove it."
