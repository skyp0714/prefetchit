#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 BINARY OUT_DIR" >&2
  exit 2
fi

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RUNNER="${ROOT}/llvm_prefetchit/scripts/run_final_proto_arena_variant.sh"
ANALYZER="${ROOT}/profiling/analyze_pebs_trace.sh"
SUMMARIZER="${ROOT}/llvm_prefetchit/tools/summarize_profile_repetition.py"
BINARY="$(readlink -f "$1")"
OUT="$(readlink -m "$2")"
REPS="${REPS:-3}"
ITERATIONS="${ITERATIONS:-400}"
WARMUP_SECONDS="${WARMUP_SECONDS:-5}"
MEASURE_DURATION="${MEASURE_DURATION:-30}"
PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD:-5000}"
MAX_ATTEMPTS_PER_REP="${MAX_ATTEMPTS_PER_REP:-3}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'

mkdir -p "${OUT}"
sha256sum "${BINARY}" >"${OUT}/profile_binary.sha256"
printf 'binary=%s\nreps=%s\niterations=%s\nwarmup_s=%s\nmeasure_duration_s=%s\nsample_period=%s\n' \
  "${BINARY}" "${REPS}" "${ITERATIONS}" "${WARMUP_SECONDS}" \
  "${MEASURE_DURATION}" "${PROFILE_SAMPLE_PERIOD}" >"${OUT}/campaign.conf"
printf 'rep,attempt,status,samples,real_time_ns,cpu_migrations,service_tids,trace_dir\n' \
  >"${OUT}/profiles.csv"

trace_args=()
for rep in $(seq 1 "${REPS}"); do
  status=failed
  for attempt in $(seq 1 "${MAX_ATTEMPTS_PER_REP}"); do
    run="${OUT}/rep${rep}_attempt${attempt}"
    trace="${run}/trace"
    rm -rf "${run}"
    set +e
    PROFILE_RECORD=1 PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD}" \
      ITERATIONS="${ITERATIONS}" WARMUP_SECONDS="${WARMUP_SECONDS}" \
      MEASURE_DURATION="${MEASURE_DURATION}" \
      "${RUNNER}" "profile_rep${rep}" "${BINARY}" "${run}"
    runner_rc="$?"
    set -e
    if ((runner_rc != 0)) || [[ ! -s "${run}/l2miss_profile.data" ]]; then
      printf '%s,%s,runner_failed,0,nan,-1,0,%s\n' \
        "${rep}" "${attempt}" "${trace}" | tee -a "${OUT}/profiles.csv"
      rm -f "${run}/l2miss_profile.data"
      continue
    fi

    mkdir -p "${trace}"
    set +e
    "${ANALYZER}" --data "${run}/l2miss_profile.data" --out-dir "${trace}" \
      --event-label "${EVENT}" --binary "${BINARY}" >"${run}/analyze.log" 2>&1
    analyzer_rc="$?"
    set -e
    samples="$(awk -F: '/LBR samples parsed \(raw\)/ {gsub(/[^0-9]/, "", $2); print $2; exit}' \
      "${trace}/trace_summary.md" 2>/dev/null || true)"
    real_time="$(jq -r '.real_time_ns // "nan"' "${run}/summary.json" 2>/dev/null || echo nan)"
    tids="$(awk -F, 'NR > 1 && $5 == "ok" {n++} END {print n+0}' \
      "${run}/benchmark_affinity.csv" 2>/dev/null || echo 0)"
    valid="$(jq -r '.valid // 0' "${run}/summary.json" 2>/dev/null || echo 0)"
    status=failed
    if ((analyzer_rc == 0)) && [[ "${valid}" == 1 && "${samples:-0}" =~ ^[0-9]+$ ]] \
      && ((samples > 0)); then
      status=ok
    fi
    printf '%s,%s,%s,%s,%s,-1,%s,%s\n' \
      "${rep}" "${attempt}" "${status}" "${samples:-0}" "${real_time}" \
      "${tids}" "${trace}" | tee -a "${OUT}/profiles.csv"
    rm -f "${run}/l2miss_profile.data"
    [[ "${status}" == ok ]] && break
  done
  [[ "${status}" == ok ]] || exit 1
  trace_args+=(--trace-dir "${trace}")
done

python3 "${SUMMARIZER}" --benchmark proto_arena \
  --out-dir "${OUT}/repetition_summary" "${trace_args[@]}"
