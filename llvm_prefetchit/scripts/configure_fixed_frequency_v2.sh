#!/usr/bin/env bash
# Frozen platform config for paper measurements (2026-08-15 rev).
# MODE=3.8ghz (default): core min=max=3.8GHz — single-core runs (Verilator).
# MODE=2ghz: core min=max=2.0GHz — multi-core runs (PostgreSQL) where 3.8
#            cannot be held on all active cores.
# Both modes pin uncore min=max per domain (uncore00/01: 2.2GHz compute,
# uncore02/03: 2.5GHz) — WITHOUT this the uncore idles at its 800MHz floor
# even under full single-core load, inflating L2->LLC code-miss latency ~17%.
# NOTE: none of this persists across reboot; re-run after every boot.
set -euo pipefail

if ((EUID != 0)); then
  echo "run as root: sudo $0" >&2
  exit 2
fi

MODE="${MODE:-3.8ghz}"

case "${MODE}" in
  3.8ghz) PERF_PCT=100; HWP_PERF=38; FREQ_KHZ=3800000; NO_TURBO=0 ;;
  2ghz)   PERF_PCT=53;  HWP_PERF=20; FREQ_KHZ=2000000; NO_TURBO=1 ;;
  *) echo "unknown MODE=${MODE} (use 3.8ghz or 2ghz)" >&2; exit 2 ;;
esac

# Turbo-enable first: configure_fixed_frequency.sh (v1) leaves
# MISC_ENABLE.TURBO_DISABLE set, which makes the no_turbo write EPERM.
x86_energy_perf_policy --cpu all --turbo-enable "$((1 - NO_TURBO))"
echo "${NO_TURBO}" > /sys/devices/system/cpu/intel_pstate/no_turbo
echo 100           > /sys/devices/system/cpu/intel_pstate/max_perf_pct
echo "${PERF_PCT}" > /sys/devices/system/cpu/intel_pstate/max_perf_pct
echo "${PERF_PCT}" > /sys/devices/system/cpu/intel_pstate/min_perf_pct

for policy in /sys/devices/system/cpu/cpufreq/policy*; do
  echo performance > "${policy}/scaling_governor"
  echo "${FREQ_KHZ}" > "${policy}/scaling_max_freq"
  echo "${FREQ_KHZ}" > "${policy}/scaling_min_freq"
done

# EPP=performance, desired pinned: rules out the HWP-boosts-low-stall-variants
# DVFS artifact that inflated the June Verilator numbers.
x86_energy_perf_policy --cpu all \
  --hwp-min "${HWP_PERF}" --hwp-max "${HWP_PERF}" \
  --hwp-desired "${HWP_PERF}" --hwp-epp 0 --turbo-enable "$((1 - NO_TURBO))"

# Uncore: package-level min writes propagate down and can wedge domain
# min>max, so lower package min first, then pin each domain min=max.
UNCORE=/sys/devices/system/cpu/intel_uncore_frequency
echo 800000 > "${UNCORE}/package_00_die_00/min_freq_khz"
for d in "${UNCORE}"/uncore0*; do
  cat "${d}/max_freq_khz" > "${d}/min_freq_khz"
done

sysctl -q -w kernel.perf_event_paranoid=-1

printf 'mode=%s core_khz=%s no_turbo=%s ' "${MODE}" "${FREQ_KHZ}" \
  "$(</sys/devices/system/cpu/intel_pstate/no_turbo)"
for d in "${UNCORE}"/uncore0*; do
  printf '%s=%s/%s ' "$(basename "${d}")" \
    "$(<"${d}/min_freq_khz")" "$(<"${d}/max_freq_khz")"
done
echo
