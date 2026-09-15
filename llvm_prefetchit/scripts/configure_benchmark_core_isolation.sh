#!/usr/bin/env bash
set -euo pipefail

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${CORE_ISOLATION_STATE_DIR:-${ROOT}/work/pgo_goal_20260713/core_isolation_state}"
HOUSEKEEPING_CPUS="${HOUSEKEEPING_CPUS:-0,71-85}"
FULL_CPUS="${FULL_CPUS:-0-85}"
HOUSEKEEPING_MASK="${HOUSEKEEPING_MASK:-3fff80,00000000,00000001}"

require_root() {
  [[ "${EUID}" -eq 0 ]] || { echo "run as root" >&2; exit 2; }
}

save_state() {
  [[ ! -e "${STATE_DIR}/enabled" ]] || return 0
  mkdir -p "${STATE_DIR}"
  : > "${STATE_DIR}/task_affinity.tsv"
  for task in /proc/[0-9]*/task/[0-9]*; do
    [[ -r "${task}/status" ]] || continue
    tid="${task##*/}"
    allowed="$(awk '/^Cpus_allowed_list:/ {print $2}' "${task}/status")"
    [[ -n "${allowed}" ]] || continue
    printf '%s\t%s\n' "${tid}" "${allowed}" >> "${STATE_DIR}/task_affinity.tsv"
  done

  : > "${STATE_DIR}/irq_affinity.tsv"
  for path in /proc/irq/*/smp_affinity_list; do
    [[ -r "${path}" ]] || continue
    printf '%s\t%s\n' "${path}" "$(<"${path}")" >> "${STATE_DIR}/irq_affinity.tsv"
  done
  cat /sys/devices/virtual/workqueue/cpumask > "${STATE_DIR}/workqueue_cpumask"
  systemctl is-active irqbalance > "${STATE_DIR}/irqbalance_state" 2>/dev/null || true
  touch "${STATE_DIR}/enabled"
}

enable_isolation() {
  require_root
  save_state
  systemctl stop irqbalance 2>/dev/null || true

  while IFS=$'\t' read -r tid _; do
    [[ -e "/proc/${tid}/status" ]] || continue
    taskset -pc "${HOUSEKEEPING_CPUS}" "${tid}" >/dev/null 2>&1 || true
  done < "${STATE_DIR}/task_affinity.tsv"

  while IFS=$'\t' read -r path _; do
    [[ -w "${path}" ]] || continue
    printf '%s\n' "${HOUSEKEEPING_CPUS}" > "${path}" 2>/dev/null || true
  done < "${STATE_DIR}/irq_affinity.tsv"
  printf '%s\n' "${HOUSEKEEPING_MASK}" > /sys/devices/virtual/workqueue/cpumask
  echo "enabled: benchmark=1-70 housekeeping=${HOUSEKEEPING_CPUS}"
}

disable_isolation() {
  require_root
  [[ -e "${STATE_DIR}/enabled" ]] || { echo "not enabled"; return 0; }
  while IFS=$'\t' read -r tid allowed; do
    [[ -e "/proc/${tid}/status" ]] || continue
    taskset -pc "${allowed}" "${tid}" >/dev/null 2>&1 || true
  done < "${STATE_DIR}/task_affinity.tsv"

  while IFS=$'\t' read -r path allowed; do
    [[ -w "${path}" ]] || continue
    printf '%s\n' "${allowed}" > "${path}" 2>/dev/null || true
  done < "${STATE_DIR}/irq_affinity.tsv"
  cat "${STATE_DIR}/workqueue_cpumask" > /sys/devices/virtual/workqueue/cpumask
  if [[ "$(<"${STATE_DIR}/irqbalance_state")" == active ]]; then
    systemctl start irqbalance
  fi
  rm -f "${STATE_DIR}/enabled"
  echo "disabled: restored recorded affinities"
}

status_isolation() {
  if [[ -e "${STATE_DIR}/enabled" ]]; then
    echo "enabled"
  else
    echo "disabled"
  fi
  echo "workqueue_cpumask=$(</sys/devices/virtual/workqueue/cpumask)"
  echo "irqbalance=$(systemctl is-active irqbalance 2>/dev/null || true)"
}

case "${1:-status}" in
  enable) enable_isolation ;;
  disable) disable_isolation ;;
  status) status_isolation ;;
  *) echo "usage: $0 {enable|disable|status}" >&2; exit 2 ;;
esac
