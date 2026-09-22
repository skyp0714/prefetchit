#!/usr/bin/env bash
# Set designated CPUs to performance governor and fix freq at max.
# Usage:
#   sudo ./set_perf_cpus.sh 0-10
#   sudo ./set_perf_cpus.sh 0-3,8,12-15
#   (no args) -> acts on all online CPUs

set -euo pipefail

need_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (try: sudo $0 ...)" >&2
    exit 1
  fi
}

# Expand a CPU selector like "0-3,8,12-15" to a list "0 1 2 3 8 12 13 14 15"
expand_cpus() {
  local sel="$1" out=()
  IFS=',' read -ra parts <<< "$sel"
  for p in "${parts[@]}"; do
    if [[ "$p" =~ ^[0-9]+-[0-9]+$ ]]; then
      IFS='-' read -r a b <<< "$p"
      for ((i=a; i<=b; i++)); do out+=("$i"); done
    elif [[ "$p" =~ ^[0-9]+$ ]]; then
      out+=("$p")
    else
      echo "Invalid CPU token: $p" >&2
      exit 1
    fi
  done
  printf "%s\n" "${out[@]}"
}

# If no selector given, use all online CPUs
get_target_cpus() {
  if [[ $# -ge 1 ]]; then
    expand_cpus "$1"
  else
    # online list like "0-15"
    local online
    online="$(< /sys/devices/system/cpu/online)"
    expand_cpus "$online"
  fi
}

set_perf_one_cpu() {
  local cpu="$1"
  local base="/sys/devices/system/cpu/cpu${cpu}"
  local cf="${base}/cpufreq"
  [[ -d "$base" ]] || return 0

  # Governor -> performance if available
  if [[ -w "${cf}/scaling_governor" ]] && \
     grep -qw performance "${cf}/scaling_available_governors" 2>/dev/null; then
    echo performance > "${cf}/scaling_governor" || true
  fi

  # Intel EPP -> performance if present
  [[ -w "${cf}/energy_performance_preference" ]] && \
    echo performance > "${cf}/energy_performance_preference" || true

  # Determine allowable freq range
  local cur_min cur_max cpu_max
  [[ -r "${cf}/scaling_max_freq" ]] && cur_max=$(<"${cf}/scaling_max_freq")
  [[ -r "${cf}/scaling_min_freq" ]] && cur_min=$(<"${cf}/scaling_min_freq")
  [[ -r "${cf}/cpuinfo_max_freq" ]] && cpu_max=$(<"${cf}/cpuinfo_max_freq")

  # Prefer the smaller of (cpuinfo_max, scaling_max) as a safe ceiling
  local target_max=""
  if [[ -n "$cpu_max" && -n "$cur_max" ]]; then
    (( cpu_max < cur_max )) && target_max="$cpu_max" || target_max="$cur_max"
  else
    target_max="${cpu_max:-$cur_max}"
  fi

  # Set max first, then min (to avoid EINVAL due to min>max)
  if [[ -n "$target_max" ]]; then
    [[ -w "${cf}/scaling_max_freq" ]] && echo "$target_max" > "${cf}/scaling_max_freq" || true
    [[ -w "${cf}/scaling_min_freq" ]] && echo "$target_max" > "${cf}/scaling_min_freq" || true
  fi

  # Do NOT touch scaling_setspeed unless governor==userspace
  # if [[ -w "${cf}/scaling_setspeed" ]] && [[ "$(cat ${cf}/scaling_governor 2>/dev/null)" == "userspace" ]]; then
  #   echo "$target_max" > "${cf}/scaling_setspeed" || true
  # fi
}

tune_intel_global() {
  local ip="/sys/devices/system/cpu/intel_pstate"
  if [[ -d "$ip" ]]; then
    [[ -w "${ip}/min_perf_pct" ]] && echo 100 > "${ip}/min_perf_pct" || true
    [[ -w "${ip}/max_perf_pct" ]] && echo 100 > "${ip}/max_perf_pct" || true
    # [[ -w "${ip}/no_turbo" ]] && echo 0 > "${ip}/no_turbo" || true  # keep turbo on
  fi
}

verify_report() {
  echo
  echo "=== Verification (driver, governor & current freq) ==="
  printf "%-4s %-10s %-12s %-8s\n" "CPU" "Driver" "Governor" "Cur(MHz)"
  for cpu in "$@"; do
    local cf="/sys/devices/system/cpu/cpu${cpu}/cpufreq"
    local drv gov cur
    drv="$(basename "$(readlink -f /sys/devices/system/cpu/cpu${cpu}/cpufreq/scaling_driver 2>/dev/null || echo /dev/null)")"
    [[ -r "${cf}/scaling_governor" ]] && gov="$(< "${cf}/scaling_governor")" || gov="(n/a)"
    if [[ -r "${cf}/scaling_cur_freq" ]]; then
      cur="$(awk '{printf "%.0f", $1/1000}' "${cf}/scaling_cur_freq")"
    else
      cur="n/a"
    fi
    printf "%-4s %-10s %-12s %-8s\n" "$cpu" "${drv:-(n/a)}" "$gov" "$cur"
  done
}

main() {
  need_root
  mapfile -t cpus < <(get_target_cpus "${1-}")
  if [[ ${#cpus[@]} -eq 0 ]]; then
    echo "No target CPUs found." >&2
    exit 1
  fi

  tune_intel_global
  for c in "${cpus[@]}"; do
    set_perf_one_cpu "$c"
  done

  verify_report "${cpus[@]}"
  echo
  echo "Done."
}

main "$@"