#!/usr/bin/env bash
set -euo pipefail

if ((EUID != 0)); then
  echo "run as root: sudo $0" >&2
  exit 2
fi

FREQ_KHZ="${FREQ_KHZ:-2000000}"
PERF_PCT="${PERF_PCT:-53}"
HWP_PERF="${HWP_PERF:-20}"

echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo
echo "${PERF_PCT}" > /sys/devices/system/cpu/intel_pstate/max_perf_pct
echo "${PERF_PCT}" > /sys/devices/system/cpu/intel_pstate/min_perf_pct

for policy in /sys/devices/system/cpu/cpufreq/policy*; do
  echo performance > "${policy}/scaling_governor"
  echo "${FREQ_KHZ}" > "${policy}/scaling_min_freq"
  echo "${FREQ_KHZ}" > "${policy}/scaling_max_freq"
done

x86_energy_perf_policy --cpu all \
  --hwp-min "${HWP_PERF}" --hwp-max "${HWP_PERF}" \
  --hwp-desired "${HWP_PERF}" --hwp-epp 128 --turbo-enable 0

printf 'configured freq_khz=%s perf_pct=%s hwp_perf=%s no_turbo=%s\n' \
  "${FREQ_KHZ}" "${PERF_PCT}" "${HWP_PERF}" \
  "$(</sys/devices/system/cpu/intel_pstate/no_turbo)"
