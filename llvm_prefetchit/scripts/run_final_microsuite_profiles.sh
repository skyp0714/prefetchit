#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 3 ]]; then
  echo "usage: $0 BENCHMARK BASELINE_BINARY OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
RUNNER="${ROOT}/llvm_prefetchit/scripts/run_final_microsuite_variant.sh"
ANALYZER="${ROOT}/profiling/analyze_pebs_trace.sh"
SUMMARIZER="${ROOT}/llvm_prefetchit/tools/summarize_profile_repetition.py"
BENCHMARK="$1"
BINARY="$(readlink -f "$2")"
PERF_TARGET_ROLE="${PERF_TARGET_ROLE:-mid}"
PROFILE_SYMBOL_BINARY="$(readlink -f "${PROFILE_SYMBOL_BINARY:-${BINARY}}")"
OUT="$(readlink -m "$3")"

REPS="${REPS:-5}"
DURATION="${DURATION:-30}"
PREWARM_DURATION="${PREWARM_DURATION:-120}"
PREWARM_DEPTH="${PREWARM_DEPTH:-64}"
MEASURE_SETTLE_DURATION="${MEASURE_SETTLE_DURATION:-25}"
GRPC_CORE_CAP="${GRPC_CORE_CAP:-6}"
DISABLE_ASLR="${DISABLE_ASLR:-0}"
ROUTER_PREPOPULATE="${ROUTER_PREPOPULATE:-0}"
ROUTER_LEAF_INSTANCES="${ROUTER_LEAF_INSTANCES:-1}"
ROUTER_FIXED_PREWARM_REQUESTS="${ROUTER_FIXED_PREWARM_REQUESTS:-0}"
ROUTER_FIXED_PREWARM_TIMEOUT="${ROUTER_FIXED_PREWARM_TIMEOUT:-180}"
EVICT_CACHES="${EVICT_CACHES:-0}"
EVICT_BYTES_PER_CORE="${EVICT_BYTES_PER_CORE:-8388608}"
EVICT_PASSES="${EVICT_PASSES:-4}"
DEPTH="${DEPTH:-32}"
PARALLELISM="${PARALLELISM:-4}"
DISPATCH="${DISPATCH:-4}"
RESPONSES="${RESPONSES:-4}"
PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD:-50000}"
MAX_ATTEMPTS_PER_REP="${MAX_ATTEMPTS_PER_REP:-3}"
EXPECTED_MID_TIDS="${EXPECTED_MID_TIDS:-0}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'

mkdir -p "${OUT}"
sha256sum "${BINARY}" > "${OUT}/profile_binary.sha256"
sha256sum "${PROFILE_SYMBOL_BINARY}" > "${OUT}/profile_symbol_binary.sha256"
printf 'benchmark=%s\nbinary=%s\nperf_target_role=%s\nprofile_symbol_binary=%s\nreps=%s\nduration_s=%s\nprewarm_duration_s=%s\nprewarm_depth=%s\nmeasure_settle_duration_s=%s\ngrpc_core_cap=%s\ndisable_aslr=%s\nrouter_prepopulate=%s\nrouter_leaf_instances=%s\nrouter_fixed_prewarm_requests=%s\nrouter_fixed_prewarm_timeout_s=%s\nevict_caches=%s\nevict_bytes_per_core=%s\nevict_passes=%s\ndepth=%s\nparallelism=%s\ndispatch=%s\nresponses=%s\nsample_period=%s\nmax_attempts_per_rep=%s\nexpected_mid_tids=%s\n' \
  "${BENCHMARK}" "${BINARY}" "${PERF_TARGET_ROLE}" "${PROFILE_SYMBOL_BINARY}" \
  "${REPS}" "${DURATION}" "${PREWARM_DURATION}" \
  "${PREWARM_DEPTH}" "${MEASURE_SETTLE_DURATION}" "${GRPC_CORE_CAP}" \
  "${DISABLE_ASLR}" "${ROUTER_PREPOPULATE}" "${ROUTER_LEAF_INSTANCES}" \
  "${ROUTER_FIXED_PREWARM_REQUESTS}" \
  "${ROUTER_FIXED_PREWARM_TIMEOUT}" \
  "${EVICT_CACHES}" "${EVICT_BYTES_PER_CORE}" "${EVICT_PASSES}" \
  "${DEPTH}" "${PARALLELISM}" \
  "${DISPATCH}" "${RESPONSES}" "${PROFILE_SAMPLE_PERIOD}" \
  "${MAX_ATTEMPTS_PER_REP}" "${EXPECTED_MID_TIDS}" > "${OUT}/campaign.conf"
printf 'rep,attempt,status,samples,qps,cpu_migrations,mid_tids,trace_dir,perf_target_role,perf_target_tids\n' \
  > "${OUT}/profiles.csv"

trace_args=()
for rep in $(seq 1 "${REPS}"); do
  attempt=0
  status=failed
  while [[ "${status}" != ok && "${attempt}" -lt "${MAX_ATTEMPTS_PER_REP}" ]]; do
    attempt=$((attempt + 1))
    run="${OUT}/rep${rep}_attempt${attempt}"
    trace="${run}/trace"
    rm -rf "${run}"
    set +e
    PERF_TARGET_ROLE="${PERF_TARGET_ROLE}" \
      PROFILE_RECORD=1 PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD}" \
      DURATION="${DURATION}" PREWARM_DURATION="${PREWARM_DURATION}" \
      PREWARM_DEPTH="${PREWARM_DEPTH}" GRPC_CORE_CAP="${GRPC_CORE_CAP}" \
      MEASURE_SETTLE_DURATION="${MEASURE_SETTLE_DURATION}" \
      DISABLE_ASLR="${DISABLE_ASLR}" ROUTER_PREPOPULATE="${ROUTER_PREPOPULATE}" \
      ROUTER_LEAF_INSTANCES="${ROUTER_LEAF_INSTANCES}" \
      ROUTER_FIXED_PREWARM_REQUESTS="${ROUTER_FIXED_PREWARM_REQUESTS}" \
      ROUTER_FIXED_PREWARM_TIMEOUT="${ROUTER_FIXED_PREWARM_TIMEOUT}" \
      EVICT_CACHES="${EVICT_CACHES}" \
      EVICT_BYTES_PER_CORE="${EVICT_BYTES_PER_CORE}" EVICT_PASSES="${EVICT_PASSES}" \
      DEPTH="${DEPTH}" PARALLELISM="${PARALLELISM}" DISPATCH="${DISPATCH}" \
      RESPONSES="${RESPONSES}" \
      "${RUNNER}" "${BENCHMARK}" "profile_rep${rep}" "${BINARY}" "${run}"
    runner_rc=$?
    set -e

    if [[ "${runner_rc}" -ne 0 || ! -s "${run}/summary.json" || \
          ! -s "${run}/l2miss_profile.data" ]]; then
      printf '%s,%s,runner_failed,0,nan,nan,0,%s,%s,0\n' \
        "${rep}" "${attempt}" "${trace}" "${PERF_TARGET_ROLE}" \
        | tee -a "${OUT}/profiles.csv"
      rm -f "${run}/l2miss_profile.data"
      continue
    fi

    mkdir -p "${trace}"
    set +e
    "${ANALYZER}" --data "${run}/l2miss_profile.data" --out-dir "${trace}" \
      --event-label "${EVENT}" --binary "${PROFILE_SYMBOL_BINARY}" \
      > "${run}/analyze.log" 2>&1
    analyzer_rc=$?
    set -e
    if [[ "${analyzer_rc}" -ne 0 || ! -s "${trace}/trace_summary.md" ]]; then
      printf '%s,%s,analyzer_failed,0,nan,nan,0,%s,%s,0\n' \
        "${rep}" "${attempt}" "${trace}" "${PERF_TARGET_ROLE}" \
        | tee -a "${OUT}/profiles.csv"
      rm -f "${run}/l2miss_profile.data"
      continue
    fi
    samples="$(awk -F: '/LBR samples parsed \(raw\)/ {gsub(/[^0-9]/, "", $2); print $2; exit}' "${trace}/trace_summary.md")"
    valid="$(jq -r '.valid' "${run}/summary.json")"
    qps="$(jq -r '.qps' "${run}/summary.json")"
    migrations="$(jq -r '.cpu_migrations' "${run}/summary.json")"
    tids="$(jq -r '.mid_tids' "${run}/summary.json")"
    perf_target_tids="$(jq -r \
      'if .perf_target_role == "leaf" then .leaf_tids else .mid_tids end' \
      "${run}/summary.json")"
    status=failed
    if [[ "${valid}" == 1 && "${samples:-0}" =~ ^[0-9]+$ && "${samples}" -gt 0 ]]; then
      if ((EXPECTED_MID_TIDS > 0)) && [[ "${tids}" -ne "${EXPECTED_MID_TIDS}" ]]; then
        status=tids_mismatch
      else
        status=ok
      fi
    fi
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
      "${rep}" "${attempt}" "${status}" "${samples:-0}" "${qps}" \
      "${migrations}" "${tids}" "${trace}" "${PERF_TARGET_ROLE}" \
      "${perf_target_tids}" | tee -a "${OUT}/profiles.csv"
    rm -f "${run}/l2miss_profile.data"
  done
  [[ "${status}" == ok ]] || exit 1
  trace_args+=(--trace-dir "${trace}")
done

python3 "${SUMMARIZER}" --benchmark "${BENCHMARK}" \
  --out-dir "${OUT}/repetition_summary" "${trace_args[@]}"
