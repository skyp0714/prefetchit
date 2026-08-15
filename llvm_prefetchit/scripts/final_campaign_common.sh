#!/usr/bin/env bash

# Shared measurement controls for the final datacenter campaign. Callers keep
# workload, load-generator, and control cores disjoint and profile the service
# PID rather than the complete launcher process tree.

FC_CONTROL_CORE="${FC_CONTROL_CORE:-0}"
FC_FREQ_KHZ="${FC_FREQ_KHZ:-2000000}"
FC_PERF_PCT="${FC_PERF_PCT:-53}"
FC_PIN_INTERVAL_SEC="${FC_PIN_INTERVAL_SEC:-0.01}"
FC_PINNER_PID=""

fc_expand_cores() {
  local spec="$1" part lo hi core
  local -A seen=()
  local -a out=()
  IFS=',' read -r -a parts <<< "${spec}"
  for part in "${parts[@]}"; do
    [[ -n "${part}" ]] || continue
    if [[ "${part}" == *-* ]]; then
      lo="${part%-*}"
      hi="${part#*-}"
      for ((core=lo; core<=hi; core++)); do
        if [[ -z "${seen[${core}]:-}" ]]; then
          seen["${core}"]=1
          out+=("${core}")
        fi
      done
    else
      if [[ -z "${seen[${part}]:-}" ]]; then
        seen["${part}"]=1
        out+=("${part}")
      fi
    fi
  done
  printf '%s\n' "${out[@]}"
}

# Turbo/boost state is driver-dependent: intel_pstate exposes no_turbo and
# perf_pct limits, acpi-cpufreq exposes a global boost flag. "1" always means
# turbo disabled here.
fc_turbo_disabled() {
  if [[ -e /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
    cat /sys/devices/system/cpu/intel_pstate/no_turbo
  elif [[ -e /sys/devices/system/cpu/cpufreq/boost ]]; then
    local boost
    boost="$(</sys/devices/system/cpu/cpufreq/boost)"
    [[ "${boost}" == 0 ]] && echo 1 || echo 0
  else
    echo unknown
  fi
}

fc_perf_pct() {
  local which="$1"
  if [[ -e "/sys/devices/system/cpu/intel_pstate/${which}_perf_pct" ]]; then
    cat "/sys/devices/system/cpu/intel_pstate/${which}_perf_pct"
  else
    echo "${FC_PERF_PCT}"
  fi
}

fc_capture_frequency_state() {
  local cores="$1" output="$2" core base governor min_freq max_freq cur_freq min_pct max_pct no_turbo
  mkdir -p "$(dirname "${output}")"
  min_pct="$(fc_perf_pct min)"
  max_pct="$(fc_perf_pct max)"
  no_turbo="$(fc_turbo_disabled)"
  printf 'cpu,governor,min_khz,max_khz,current_khz,no_turbo,min_perf_pct,max_perf_pct\n' > "${output}"
  while read -r core; do
    base="/sys/devices/system/cpu/cpu${core}/cpufreq"
    governor="$(<"${base}/scaling_governor")"
    min_freq="$(<"${base}/scaling_min_freq")"
    max_freq="$(<"${base}/scaling_max_freq")"
    cur_freq="$(<"${base}/scaling_cur_freq")"
    printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
      "${core}" "${governor}" "${min_freq}" "${max_freq}" "${cur_freq}" \
      "${no_turbo}" "${min_pct}" "${max_pct}" >> "${output}"
  done < <(fc_expand_cores "${cores}")
}

fc_assert_frequency() {
  local cores="$1" output="$2" core base governor min_freq max_freq no_turbo min_pct max_pct bad=0
  fc_capture_frequency_state "${cores}" "${output}"
  no_turbo="$(fc_turbo_disabled)"
  min_pct="$(fc_perf_pct min)"
  max_pct="$(fc_perf_pct max)"
  while read -r core; do
    base="/sys/devices/system/cpu/cpu${core}/cpufreq"
    governor="$(<"${base}/scaling_governor")"
    min_freq="$(<"${base}/scaling_min_freq")"
    max_freq="$(<"${base}/scaling_max_freq")"
    if [[ "${governor}" != "performance" || "${min_freq}" != "${FC_FREQ_KHZ}" || \
          "${max_freq}" != "${FC_FREQ_KHZ}" || "${no_turbo}" != 1 || \
          "${min_pct}" != "${FC_PERF_PCT}" || "${max_pct}" != "${FC_PERF_PCT}" ]]; then
      printf '[freq-error] cpu=%s governor=%s min=%s max=%s no_turbo=%s perf_pct=%s/%s expected=%s/no_turbo=1/perf_pct=%s\n' \
        "${core}" "${governor}" "${min_freq}" "${max_freq}" "${no_turbo}" \
        "${min_pct}" "${max_pct}" "${FC_FREQ_KHZ}" "${FC_PERF_PCT}" >&2
      bad=1
    fi
  done < <(fc_expand_cores "${cores}")
  return "${bad}"
}

fc_start_pinner() {
  local pid="$1" core_spec="$2" log="$3"
  mkdir -p "$(dirname "${log}")"
  : > "${log}"
  taskset -c "${FC_CONTROL_CORE}" bash -c '
    set -u
    pid="$1"
    core_spec="$2"
    log="$3"
    interval="$4"
    declare -A assigned=()
    declare -A used_core=()
    cores=()
    IFS="," read -r -a parts <<< "${core_spec}"
    for part in "${parts[@]}"; do
      if [[ "${part}" == *-* ]]; then
        lo="${part%-*}"; hi="${part#*-}"
        for ((core=lo; core<=hi; core++)); do cores+=("${core}"); done
      else
        cores+=("${part}")
      fi
    done
    while kill -0 "${pid}" 2>/dev/null; do
      mapfile -t tids < <(ps -L -o tid= -p "${pid}" 2>/dev/null | awk "{print \$1}")
      for tid in "${tids[@]}"; do
        [[ -n "${tid}" ]] || continue
        core="${assigned[${tid}]:-}"
        if [[ -z "${core}" ]]; then
          core=""
          current_allowed="$(awk "/Cpus_allowed_list/ {print \$2}" "/proc/${pid}/task/${tid}/status" 2>/dev/null || true)"
          for candidate in "${cores[@]}"; do
            owner="${used_core[${candidate}]:-}"
            if [[ -n "${owner}" && ! -d "/proc/${pid}/task/${owner}" ]]; then
              unset "assigned[${owner}]"
              unset "used_core[${candidate}]"
            fi
            if [[ "${current_allowed}" == "${candidate}" && -z "${used_core[${candidate}]:-}" ]]; then
              core="${candidate}"
              break
            fi
          done
          for candidate in "${cores[@]}"; do
            [[ -z "${core}" ]] || break
            if [[ -z "${used_core[${candidate}]:-}" ]]; then
              core="${candidate}"
              break
            fi
          done
          if [[ -z "${core}" ]]; then
            printf "[%(%F %T)T] ERROR no-free-core pid=%s tid=%s active_tids=%s cores=%s\n" \
              -1 "${pid}" "${tid}" "${#tids[@]}" "${core_spec}" >> "${log}"
            continue
          fi
          assigned["${tid}"]="${core}"
          used_core["${core}"]="${tid}"
          comm="$(cat "/proc/${pid}/task/${tid}/comm" 2>/dev/null || true)"
          printf "[%(%F %T)T] assign pid=%s tid=%s comm=%s core=%s\n" \
            -1 "${pid}" "${tid}" "${comm}" "${core}" >> "${log}"
        fi
        current_allowed="$(awk "/Cpus_allowed_list/ {print \$2}" "/proc/${pid}/task/${tid}/status" 2>/dev/null || true)"
        if [[ "${current_allowed}" == "${core}" ]]; then
          continue
        fi
        if ! taskset -pc "${core}" "${tid}" >/dev/null 2>&1; then
          if [[ -d "/proc/${pid}/task/${tid}" ]]; then
            printf "[%(%F %T)T] ERROR taskset-failed pid=%s tid=%s core=%s\n" -1 "${pid}" "${tid}" "${core}" >> "${log}"
          else
            printf "[%(%F %T)T] WARN taskset-raced-thread-exit pid=%s tid=%s core=%s\n" -1 "${pid}" "${tid}" "${core}" >> "${log}"
          fi
        else
          printf "[%(%F %T)T] CORRECT repin pid=%s tid=%s from=%s to=%s\n" \
            -1 "${pid}" "${tid}" "${current_allowed:-unknown}" "${core}" >> "${log}"
        fi
      done
      for tid in "${!assigned[@]}"; do
        if [[ ! -d "/proc/${pid}/task/${tid}" ]]; then
          core="${assigned[${tid}]}"
          unset "assigned[${tid}]"
          unset "used_core[${core}]"
        fi
      done
      sleep "${interval}"
    done
  ' _ "${pid}" "${core_spec}" "${log}" "${FC_PIN_INTERVAL_SEC}" &
  FC_PINNER_PID="$!"
}

fc_start_tree_pinner() {
  local root_pid="$1" core_spec="$2" log="$3"
  mkdir -p "$(dirname "${log}")"
  : > "${log}"
  (
    declare -A assigned=() used_core=()
    local interval="${FC_PIN_INTERVAL_SEC}"
    local ignored_re='^(perf|taskset|timeout|bash|sh|run-memcached|sleep|ps|awk|pgrep|sed|tr|tee|time)$'
    local pids frontier next parent children pid_csv pid tid comm core candidate lo hi part
    local -a cores=() parts=()
    cores=()
    IFS=',' read -r -a parts <<< "${core_spec}"
    for part in "${parts[@]}"; do
      if [[ "${part}" == *-* ]]; then
        lo="${part%-*}"; hi="${part#*-}"
        for ((core=lo; core<=hi; core++)); do cores+=("${core}"); done
      else
        cores+=("${part}")
      fi
    done
    while kill -0 "${root_pid}" 2>/dev/null; do
      pids="${root_pid}"; frontier="${root_pid}"
      while [[ -n "${frontier}" ]]; do
        next=""
        for parent in ${frontier}; do
          children="$(pgrep -P "${parent}" 2>/dev/null || true)"
          if [[ -n "${children}" ]]; then
            next+=" ${children}"; pids+=" ${children}"
          fi
        done
        frontier="${next}"
      done
      pid_csv="$(tr -s '[:space:]' ',' <<< "${pids}" | sed "s/^,*//;s/,*$//;s/,,*/,/g")"
      while read -r pid tid comm; do
        [[ -n "${tid}" ]] || continue
        [[ "${comm}" =~ ${ignored_re} ]] && continue
        core="${assigned[${tid}]:-}"
        if [[ -z "${core}" ]]; then
          core=""
          current_allowed="$(awk '/Cpus_allowed_list/ {print $2}' "/proc/${pid}/task/${tid}/status" 2>/dev/null || true)"
          for candidate in "${cores[@]}"; do
            owner="${used_core[${candidate}]:-}"
            if [[ -n "${owner}" && ! -d "/proc/${owner}" && ! -d "/proc/${root_pid}/task/${owner}" ]]; then
              unset "assigned[${owner}]"
              unset "used_core[${candidate}]"
            fi
            if [[ "${current_allowed}" == "${candidate}" && -z "${used_core[${candidate}]:-}" ]]; then
              core="${candidate}"
              break
            fi
          done
          for candidate in "${cores[@]}"; do
            [[ -z "${core}" ]] || break
            if [[ -z "${used_core[${candidate}]:-}" ]]; then core="${candidate}"; break; fi
          done
          if [[ -z "${core}" ]]; then
            printf "[%(%F %T)T] ERROR no-free-core pid=%s tid=%s comm=%s cores=%s\n" \
              -1 "${pid}" "${tid}" "${comm}" "${core_spec}" >> "${log}"
            continue
          fi
          assigned["${tid}"]="${core}"; used_core["${core}"]="${tid}"
          printf "[%(%F %T)T] assign pid=%s tid=%s comm=%s core=%s\n" \
            -1 "${pid}" "${tid}" "${comm}" "${core}" >> "${log}"
        fi
        current_allowed="$(awk '/Cpus_allowed_list/ {print $2}' "/proc/${pid}/task/${tid}/status" 2>/dev/null || true)"
        if [[ "${current_allowed}" == "${core}" ]]; then
          continue
        fi
        if ! taskset -pc "${core}" "${tid}" >/dev/null 2>&1; then
          if [[ -d "/proc/${pid}/task/${tid}" || -d "/proc/${tid}" ]]; then
            printf "[%(%F %T)T] ERROR taskset-failed pid=%s tid=%s core=%s\n" \
              -1 "${pid}" "${tid}" "${core}" >> "${log}"
          else
            printf "[%(%F %T)T] WARN taskset-raced-thread-exit pid=%s tid=%s core=%s\n" \
              -1 "${pid}" "${tid}" "${core}" >> "${log}"
          fi
        else
          printf "[%(%F %T)T] CORRECT repin pid=%s tid=%s from=%s to=%s\n" \
            -1 "${pid}" "${tid}" "${current_allowed:-unknown}" "${core}" >> "${log}"
        fi
      done < <(ps -eLo pid,tid,comm 2>/dev/null | awk -v pids="${pid_csv}" '
        BEGIN { split(pids, p, ","); for (i in p) allow[p[i]]=1 }
        NR > 1 && allow[$1] { print $1, $2, $3 }
      ')
      for tid in "${!assigned[@]}"; do
        [[ -d "/proc/${tid}" || -d "/proc/${root_pid}/task/${tid}" ]] && continue
        core="${assigned[${tid}]}"; unset "assigned[${tid}]"; unset "used_core[${core}]"
      done
      sleep "${interval}"
    done
  ) &
  FC_PINNER_PID="$!"
  taskset -pc "${FC_CONTROL_CORE}" "${FC_PINNER_PID}" >/dev/null 2>&1 || true
}

fc_collect_tree_pids() {
  local root_pid="$1" pids frontier next parent children
  pids="${root_pid}"
  frontier="${root_pid}"
  while [[ -n "${frontier}" ]]; do
    next=""
    for parent in ${frontier}; do
      children="$(pgrep -P "${parent}" 2>/dev/null || true)"
      if [[ -n "${children}" ]]; then
        next+=" ${children}"
        pids+=" ${children}"
      fi
    done
    frontier="${next}"
  done
  tr ' ' '\n' <<< "${pids}" | awk 'NF && !seen[$1]++'
}

fc_audit_tree_affinity() {
  local root_pid="$1" core_spec="$2" output="$3"
  local pid_csv pid tid psr comm allowed bad=0 seen=0
  local ignored_re='^(perf|taskset|timeout|bash|sh|run-memcached|sleep|ps|awk|pgrep|sed|tr|tee|time)$'
  local -A allowed_core=() seen_core=()

  while read -r core; do allowed_core["${core}"]=1; done < <(fc_expand_cores "${core_spec}")
  pid_csv="$(fc_collect_tree_pids "${root_pid}" | paste -sd, -)"
  mkdir -p "$(dirname "${output}")"
  printf 'pid,tid,comm,allowed_list,current_cpu,status\n' > "${output}"

  while read -r pid tid psr comm; do
    [[ -n "${tid}" ]] || continue
    [[ "${comm}" =~ ${ignored_re} ]] && continue
    seen=$((seen + 1))
    allowed="$(awk '/Cpus_allowed_list/ {print $2}' "/proc/${pid}/task/${tid}/status" 2>/dev/null || true)"
    if [[ "${allowed}" == *','* || "${allowed}" == *'-'* || -z "${allowed_core[${allowed}]:-}" ]]; then
      printf '%s,%s,%s,%s,%s,invalid-mask\n' "${pid}" "${tid}" "${comm}" "${allowed}" "${psr}" >> "${output}"
      bad=1
    elif [[ -n "${seen_core[${allowed}]:-}" ]]; then
      printf '%s,%s,%s,%s,%s,core-collision\n' "${pid}" "${tid}" "${comm}" "${allowed}" "${psr}" >> "${output}"
      bad=1
    else
      seen_core["${allowed}"]="${tid}"
      printf '%s,%s,%s,%s,%s,ok\n' "${pid}" "${tid}" "${comm}" "${allowed}" "${psr}" >> "${output}"
    fi
  done < <(ps -eLo pid=,tid=,psr=,comm= 2>/dev/null | awk -v pids="${pid_csv}" '
    BEGIN { split(pids, p, ","); for (i in p) allow[p[i]]=1 }
    allow[$1] { print $1, $2, $3, $4 }
  ')

  if ((seen == 0)); then
    printf '%s,,,,,no-live-benchmark-tasks\n' "${root_pid}" >> "${output}"
    bad=1
  fi
  return "${bad}"
}

fc_audit_pid_affinity() {
  local pid="$1" core_spec="$2" output="$3" tid allowed psr core bad=0
  local -A allowed_core=() seen_core=()
  while read -r core; do allowed_core["${core}"]=1; done < <(fc_expand_cores "${core_spec}")
  mkdir -p "$(dirname "${output}")"
  printf 'pid,tid,allowed_list,current_cpu,status\n' > "${output}"
  while read -r tid psr; do
    [[ -n "${tid}" ]] || continue
    allowed="$(awk '/Cpus_allowed_list/ {print $2}' "/proc/${pid}/task/${tid}/status" 2>/dev/null || true)"
    if [[ "${allowed}" == *','* || "${allowed}" == *'-'* || -z "${allowed_core[${allowed}]:-}" ]]; then
      printf '%s,%s,%s,%s,invalid-mask\n' "${pid}" "${tid}" "${allowed}" "${psr}" >> "${output}"
      bad=1
    elif [[ -n "${seen_core[${allowed}]:-}" ]]; then
      printf '%s,%s,%s,%s,core-collision\n' "${pid}" "${tid}" "${allowed}" "${psr}" >> "${output}"
      bad=1
    else
      seen_core["${allowed}"]="${tid}"
      printf '%s,%s,%s,%s,ok\n' "${pid}" "${tid}" "${allowed}" "${psr}" >> "${output}"
    fi
  done < <(ps -L -o tid=,psr= -p "${pid}" 2>/dev/null)
  return "${bad}"
}

fc_wait_for_stable_pinning() {
  local pid="$1" core_spec="$2" output="$3" timeout_sec="${4:-20}"
  local deadline=$((SECONDS + timeout_sec)) previous=-1 stable=0 current
  while ((SECONDS < deadline)); do
    current="$(ps -L -o tid= -p "${pid}" 2>/dev/null | awk 'NF {n++} END {print n+0}')"
    if [[ "${current}" == "${previous}" && "${current}" -gt 0 ]]; then
      stable=$((stable + 1))
    else
      stable=0
    fi
    if ((stable >= 5)); then
      fc_audit_pid_affinity "${pid}" "${core_spec}" "${output}"
      return $?
    fi
    previous="${current}"
    sleep 0.1
  done
  printf 'pid,tid,allowed_list,current_cpu,status\n%s,,,,stabilization-timeout\n' "${pid}" > "${output}"
  return 1
}

fc_stop_pinner() {
  if [[ -n "${FC_PINNER_PID}" ]]; then
    kill "${FC_PINNER_PID}" >/dev/null 2>&1 || true
    wait "${FC_PINNER_PID}" >/dev/null 2>&1 || true
    FC_PINNER_PID=""
  fi
}

fc_kill_pid() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] || return 0
  kill "${pid}" >/dev/null 2>&1 || true
  for _ in {1..20}; do
    kill -0 "${pid}" 2>/dev/null || return 0
    sleep 0.05
  done
  kill -9 "${pid}" >/dev/null 2>&1 || true
}
