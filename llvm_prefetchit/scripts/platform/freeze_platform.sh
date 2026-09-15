#!/usr/bin/env bash
# freeze_platform.sh — frozen-platform configuration for every measurement.
#
# Supersedes configure_fixed_frequency.sh (v1) and configure_fixed_frequency_v2.sh:
# one script, both cpufreq drivers.
#
#   MODE=2ghz    core min=max=2.0 GHz, turbo off, uncore min=max  (multi-core services)
#   MODE=3.8ghz  core min=max=3.8 GHz (needs intel_pstate/HWP), uncore min=max
#                (single-core Verilator/JCodeStream runs)
#   MODE=restore put cpufreq/uncore back to the boot defaults recorded by the driver
#   MODE=show    print the current state and exit 0/1 (1 = not frozen)
#
# Why: without a pinned uncore the mesh idles at its 800 MHz floor under
# single-core load and the baseline's demand code misses look ~17% slower than
# they are; without a pinned core clock the prefetch arm gets credit for waking
# DVFS. See llvm_prefetchit/results/paper_goal_20260815/CONFIG_LOG.md.
#
# Nothing here persists across reboot; run it after every boot.
set -euo pipefail

MODE="${MODE:-${1:-2ghz}}"
CPUFREQ=/sys/devices/system/cpu/cpufreq
UNCORE=/sys/devices/system/cpu/intel_uncore_frequency
DRIVER="$(</sys/devices/system/cpu/cpu0/cpufreq/scaling_driver)"

if [[ "${MODE}" != show ]] && ((EUID != 0)); then
  echo "run as root: sudo MODE=${MODE} $0" >&2
  exit 2
fi

turbo_state() {
  # prints 1 when turbo/boost is DISABLED (matches campaign_common fc_turbo_disabled)
  if [[ -e /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
    cat /sys/devices/system/cpu/intel_pstate/no_turbo
  elif [[ -e "${CPUFREQ}/boost" ]]; then
    [[ "$(<"${CPUFREQ}/boost")" == 0 ]] && echo 1 || echo 0
  else
    echo unknown
  fi
}

show_state() {
  local p0="${CPUFREQ}/policy0"
  printf 'driver=%s governor=%s min=%s max=%s cur=%s no_turbo=%s' \
    "${DRIVER}" "$(<"${p0}/scaling_governor")" "$(<"${p0}/scaling_min_freq")" \
    "$(<"${p0}/scaling_max_freq")" "$(<"${p0}/scaling_cur_freq")" "$(turbo_state)"
  if [[ -d "${UNCORE}" ]]; then
    for d in "${UNCORE}"/uncore0*; do
      printf ' %s=%s/%s' "$(basename "${d}")" "$(<"${d}/min_freq_khz")" "$(<"${d}/max_freq_khz")"
    done
  fi
  printf ' perf_event_paranoid=%s\n' "$(</proc/sys/kernel/perf_event_paranoid)"
}

set_core_all() {
  local governor="$1" min_khz="$2" max_khz="$3"
  for policy in "${CPUFREQ}"/policy*; do
    echo "${governor}" > "${policy}/scaling_governor"
    # order matters: raising max before min avoids transient min>max EINVAL
    echo "${max_khz}" > "${policy}/scaling_max_freq"
    echo "${min_khz}" > "${policy}/scaling_min_freq"
    echo "${max_khz}" > "${policy}/scaling_max_freq"
  done
}

pin_uncore() {
  [[ -d "${UNCORE}" ]] || { echo "[warn] no intel_uncore_frequency sysfs; uncore left floating" >&2; return; }
  # Package-level min propagates down and can wedge domain min>max, so lower
  # the package floor first, then pin each domain min=max.
  if [[ -e "${UNCORE}/package_00_die_00/min_freq_khz" ]]; then
    echo 800000 > "${UNCORE}/package_00_die_00/min_freq_khz"
  fi
  for d in "${UNCORE}"/uncore0*; do
    cat "${d}/max_freq_khz" > "${d}/min_freq_khz"
  done
}

restore_uncore() {
  [[ -d "${UNCORE}" ]] || return
  for d in "${UNCORE}"/uncore0*; do
    cat "${d}/initial_min_freq_khz" > "${d}/min_freq_khz"
    cat "${d}/initial_max_freq_khz" > "${d}/max_freq_khz"
  done
}

case "${MODE}" in
  show)
    show_state
    p0="${CPUFREQ}/policy0"
    [[ "$(<"${p0}/scaling_min_freq")" == "$(<"${p0}/scaling_max_freq")" ]]
    exit $?
    ;;
  2ghz)
    FREQ_KHZ=2000000; NO_TURBO=1 ;;
  3.8ghz)
    FREQ_KHZ=3800000; NO_TURBO=0
    if [[ "${DRIVER}" != intel_pstate ]]; then
      echo "[err] MODE=3.8ghz needs intel_pstate (HWP). Driver is ${DRIVER}:" >&2
      echo "      remove 'intel_pstate=disable' from the kernel command line and reboot." >&2
      exit 3
    fi ;;
  restore)
    if [[ "${DRIVER}" == intel_pstate ]]; then
      echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo
      echo 100 > /sys/devices/system/cpu/intel_pstate/max_perf_pct
      echo 0 > /sys/devices/system/cpu/intel_pstate/min_perf_pct
      x86_energy_perf_policy --cpu all --hwp-epp 128 --turbo-enable 1 >/dev/null 2>&1 || true
    else
      [[ -e "${CPUFREQ}/boost" ]] && echo 1 > "${CPUFREQ}/boost"
    fi
    # boot defaults on this host: intel_pstate → powersave (HWP), acpi-cpufreq → performance
    default_governor=$([[ "${DRIVER}" == intel_pstate ]] && echo powersave || echo performance)
    for policy in "${CPUFREQ}"/policy*; do
      cat "${policy}/cpuinfo_max_freq" > "${policy}/scaling_max_freq"
      cat "${policy}/cpuinfo_min_freq" > "${policy}/scaling_min_freq"
      echo "${default_governor}" > "${policy}/scaling_governor"
    done
    restore_uncore
    show_state
    exit 0 ;;
  *)
    echo "unknown MODE=${MODE} (2ghz | 3.8ghz | restore | show)" >&2; exit 2 ;;
esac

if [[ "${DRIVER}" == intel_pstate ]]; then
  PERF_PCT=$(( FREQ_KHZ == 3800000 ? 100 : 53 ))
  HWP_PERF=$(( FREQ_KHZ / 100000 ))
  # v1 left MISC_ENABLE.TURBO_DISABLE set, which makes the no_turbo write EPERM:
  # re-enable through the MSR first, then set the sysfs knob explicitly.
  x86_energy_perf_policy --cpu all --turbo-enable "$((1 - NO_TURBO))"
  echo "${NO_TURBO}" > /sys/devices/system/cpu/intel_pstate/no_turbo
  echo 100 > /sys/devices/system/cpu/intel_pstate/max_perf_pct
  echo "${PERF_PCT}" > /sys/devices/system/cpu/intel_pstate/max_perf_pct
  echo "${PERF_PCT}" > /sys/devices/system/cpu/intel_pstate/min_perf_pct
  set_core_all performance "${FREQ_KHZ}" "${FREQ_KHZ}"
  # EPP=performance with desired pinned rules out HWP boosting low-stall arms.
  x86_energy_perf_policy --cpu all \
    --hwp-min "${HWP_PERF}" --hwp-max "${HWP_PERF}" \
    --hwp-desired "${HWP_PERF}" --hwp-epp 0 --turbo-enable "$((1 - NO_TURBO))"
else
  # acpi-cpufreq: only P-state table entries are settable; turbo is the global boost flag.
  if ! grep -qw "${FREQ_KHZ}" "${CPUFREQ}/policy0/scaling_available_frequencies"; then
    echo "[err] ${FREQ_KHZ} kHz is not in scaling_available_frequencies:" >&2
    cat "${CPUFREQ}/policy0/scaling_available_frequencies" >&2
    exit 3
  fi
  [[ -e "${CPUFREQ}/boost" ]] && echo "$((1 - NO_TURBO))" > "${CPUFREQ}/boost"
  set_core_all performance "${FREQ_KHZ}" "${FREQ_KHZ}"
fi

pin_uncore
sysctl -q -w kernel.perf_event_paranoid=-1
sysctl -q -w kernel.kptr_restrict=0
show_state
