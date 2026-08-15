#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-}"
if [[ -z "${OUT_DIR}" ]]; then
  echo "usage: configure_perf_env.sh <out-dir>" >&2
  exit 1
fi
mkdir -p "${OUT_DIR}"
LOG="${OUT_DIR}/perf_env.log"
: > "${LOG}"

log() { echo "$*" | tee -a "${LOG}"; }

log "[inf] date=$(date)"
log "[inf] user=$(id -un)"
log "[inf] kernel=$(uname -a)"
log "[inf] nproc=$(nproc)"

governor_snapshot() {
  local out=""
  local f
  for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    [[ -r "${f}" ]] || continue
    out+="${f#/sys/devices/system/cpu/}:$(cat "${f}") "
  done
  printf '%s' "${out% }"
}

if [[ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]]; then
  log "[before] governors=$(governor_snapshot)"
else
  log "[warn] cpufreq scaling_governor not readable"
fi

if [[ -r /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
  log "[before] intel_pstate_no_turbo=$(cat /sys/devices/system/cpu/intel_pstate/no_turbo)"
fi

if [[ "${EUID}" -ne 0 ]]; then
  log "[warn] not root; frequency settings are recorded but not changed"
  exit 0
fi

for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  [[ -w "${f}" ]] || continue
  echo performance > "${f}" || true
done

if [[ -w /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
  # Disable turbo for repeatability. Existing value is recorded above.
  echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo || true
fi

if [[ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]]; then
  log "[after] governors=$(governor_snapshot)"
fi
if [[ -r /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
  log "[after] intel_pstate_no_turbo=$(cat /sys/devices/system/cpu/intel_pstate/no_turbo)"
fi
