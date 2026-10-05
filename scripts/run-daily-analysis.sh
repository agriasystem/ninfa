#!/usr/bin/env bash
# NINFA daily analysis wrapper - the ONE command an external scheduler runs (Gate 27B).
#
# Supported V1 sequence (docs/operations/pilot-daily-operations-v1.md):
#
#   1. python -m worker dispatch-analysis   evaluate the automatic-analysis policy of every enabled
#                                           property and enqueue one job per eligible property
#   2. python -m worker run --once          process every queued job, then exit
#   3. python -m worker analysis-status     print, per enabled property, whether today's run exists
#
# THE SCHEDULER: not configured by this repository. It must run this script at 10:00 in the
# NAMED timezone Europe/Rome every day (never a fixed UTC time: that is wrong twice a year when
# daylight saving changes). Running it later the same local day is supported (manual catch-up).
#
# ENVIRONMENT: loaded EXTERNALLY - by the scheduler (for example systemd `EnvironmentFile=`) or by
# `scripts/with-env.sh /etc/ninfa/api.env scripts/run-daily-analysis.sh`. This script never reads or
# prints credentials. It needs DATABASE_URL and APP_ENV=production.
#
# WORKING DIRECTORY: NINFA_APP_DIR, default = the repository root (the parent of this scripts/
# directory). NINFA_PYTHON defaults to $NINFA_APP_DIR/.venv/bin/python.
#
# HONEST LIMITATION - read this: the exit codes below do NOT prove that every analysis succeeded.
# `worker run --once` exits 0 even when a queued job failed, and `analysis-status` exits 0 even
# when an enabled property has no run today. A zero exit means "the three commands ran". The
# operator must read the analysis-status output (run_today=YES for every enabled property) at
# about 10:15. This script does not parse that human-readable output.
#
# Exit codes: 0 = all three commands exited 0; 1 = at least one command exited non-zero (all three
# are still attempted, in order); 2 = refused to start (configuration problem), nothing was run.
set -euo pipefail

log() {
  printf '%s [run-daily-analysis] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

refuse() {
  log "REFUSED: $*"
  exit 2
}

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
NINFA_APP_DIR=${NINFA_APP_DIR:-$(cd -- "${script_dir}/.." && pwd)}
NINFA_PYTHON=${NINFA_PYTHON:-${NINFA_APP_DIR}/.venv/bin/python}

[[ -d $NINFA_APP_DIR ]] || refuse "NINFA_APP_DIR is not a directory: ${NINFA_APP_DIR}"
[[ -x $NINFA_PYTHON ]] || refuse "NINFA_PYTHON is not executable: ${NINFA_PYTHON}"
[[ -n ${DATABASE_URL:-} ]] || refuse "DATABASE_URL is not set (load the API env file externally)"
[[ ${APP_ENV:-} == "production" ]] || refuse "APP_ENV must be production (got '${APP_ENV:-unset}')"
[[ -z ${TEST_DATABASE_URL:-} ]] || refuse "TEST_DATABASE_URL must never be set on a production host"

cd -- "$NINFA_APP_DIR"
log "START app_dir=${NINFA_APP_DIR} app_env=${APP_ENV}"

failed=0
summary=()

run_step() {
  local name=$1
  shift
  local rc=0
  log "STEP ${name} START"
  "$@" || rc=$?
  log "STEP ${name} END exit_code=${rc}"
  summary+=("${name}=${rc}")
  if [[ $rc -ne 0 ]]; then
    failed=1
  fi
}

run_step dispatch-analysis "$NINFA_PYTHON" -m worker dispatch-analysis
run_step worker-run-once "$NINFA_PYTHON" -m worker run --once
run_step analysis-status "$NINFA_PYTHON" -m worker analysis-status

log "SUMMARY ${summary[*]}"
log "NOTE exit codes do not prove every analysis succeeded: check run_today=YES in the analysis-status output above"
if [[ $failed -ne 0 ]]; then
  log "END result=FAILED (at least one command exited non-zero)"
  exit 1
fi
log "END result=COMMANDS_OK"
exit 0
