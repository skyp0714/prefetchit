#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 memcached|postgresql BINARY OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
BENCHMARK="$1"
BINARY="$(readlink -f "$2")"
OUT="$(readlink -m "$3")"
ANALYZER="${ROOT}/profiling/analyze_pebs_trace.sh"
SUMMARIZER="${ROOT}/llvm_prefetchit/tools/summarize_profile_repetition.py"
REPS="${REPS:-3}"
DURATION="${DURATION:-30}"
PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD:-10000}"
MAX_ATTEMPTS_PER_REP="${MAX_ATTEMPTS_PER_REP:-4}"
POSTGRES_CLIENTS="${POSTGRES_CLIENTS:-8}"
POSTGRES_CLIENT_THREADS="${POSTGRES_CLIENT_THREADS:-${POSTGRES_CLIENTS}}"
POSTGRES_QUERY_MODE="${POSTGRES_QUERY_MODE:-prepared}"
POSTGRES_PGBENCH_BUILTIN="${POSTGRES_PGBENCH_BUILTIN:-tpcb-like}"
POSTGRES_WARMUP_DURATION="${POSTGRES_WARMUP_DURATION:-20}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp'

case "${BENCHMARK}" in
  memcached)
    RUNNER="${ROOT}/llvm_prefetchit/scripts/run_final_memcached_variant.sh"
    ;;
  postgresql)
    RUNNER="${ROOT}/llvm_prefetchit/scripts/run_final_postgresql_variant.sh"
    ;;
  *)
    echo "unsupported database: ${BENCHMARK}" >&2
    exit 2
    ;;
esac

mkdir -p "${OUT}"
sha256sum "${BINARY}" > "${OUT}/profile_binary.sha256"
printf 'benchmark=%s\nbinary=%s\nreps=%s\nduration_s=%s\nsample_period=%s\nmax_attempts_per_rep=%s\n' \
  "${BENCHMARK}" "${BINARY}" "${REPS}" "${DURATION}" \
  "${PROFILE_SAMPLE_PERIOD}" "${MAX_ATTEMPTS_PER_REP}" > "${OUT}/campaign.conf"
if [[ "${BENCHMARK}" == postgresql ]]; then
  printf 'clients=%s\nclient_threads=%s\nquery_mode=%s\npgbench_builtin=%s\nwarmup_duration_s=%s\n' \
    "${POSTGRES_CLIENTS}" "${POSTGRES_CLIENT_THREADS}" \
    "${POSTGRES_QUERY_MODE}" "${POSTGRES_PGBENCH_BUILTIN}" \
    "${POSTGRES_WARMUP_DURATION}" >> "${OUT}/campaign.conf"
fi
printf 'rep,attempt,status,samples,metric,cpu_migrations,service_tids,trace_dir\n' \
  > "${OUT}/profiles.csv"

trace_args=()
for rep in $(seq 1 "${REPS}"); do
  status=failed
  for attempt in $(seq 1 "${MAX_ATTEMPTS_PER_REP}"); do
    run="${OUT}/rep${rep}_attempt${attempt}"
    trace="${run}/trace"
    rm -rf "${run}"
    set +e
    if [[ "${BENCHMARK}" == memcached ]]; then
      PROFILE_RECORD=1 PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD}" \
        DURATION="${DURATION}" WARMUP_DURATION=20 SERVICE_THREADS=8 \
        CLIENT_THREADS=4 CONNECTIONS_PER_THREAD=100 DATA_SIZE=1024 \
        READ_WRITE_RATIO=0:1 KEY_PATTERN=R:R KEY_MAX=100000 \
        HASHPOWER=14 NO_HASH_EXPAND=1 \
        "${RUNNER}" "profile_rep${rep}" "${BINARY}" "${run}"
    else
      PROFILE_RECORD=1 PROFILE_SAMPLE_PERIOD="${PROFILE_SAMPLE_PERIOD}" \
        DURATION="${DURATION}" WARMUP_DURATION="${POSTGRES_WARMUP_DURATION}" \
        CLIENTS="${POSTGRES_CLIENTS}" \
        CLIENT_THREADS="${POSTGRES_CLIENT_THREADS}" \
        QUERY_MODE="${POSTGRES_QUERY_MODE}" \
        PGBENCH_BUILTIN="${POSTGRES_PGBENCH_BUILTIN}" \
        "${RUNNER}" "profile_rep${rep}" "${BINARY}" "${run}"
    fi
    runner_rc="$?"
    set -e

    if [[ "${runner_rc}" -ne 0 || ! -s "${run}/summary.json" || \
          ! -s "${run}/l2miss_profile.data" ]]; then
      printf '%s,%s,runner_failed,0,nan,nan,0,%s\n' \
        "${rep}" "${attempt}" "${trace}" | tee -a "${OUT}/profiles.csv"
      rm -f "${run}/l2miss_profile.data"
      continue
    fi

    mkdir -p "${trace}"
    set +e
    "${ANALYZER}" --data "${run}/l2miss_profile.data" --out-dir "${trace}" \
      --event-label "${EVENT}" --binary "${BINARY}" > "${run}/analyze.log" 2>&1
    analyzer_rc="$?"
    set -e
    if [[ "${analyzer_rc}" -ne 0 || ! -s "${trace}/lbr_symbolic_dump.txt" || \
          ! -s "${trace}/lbr_raw_dump.txt" ]]; then
      printf '%s,%s,analyzer_failed,0,nan,nan,0,%s\n' \
        "${rep}" "${attempt}" "${trace}" | tee -a "${OUT}/profiles.csv"
      rm -f "${run}/l2miss_profile.data"
      continue
    fi

    samples="$(awk -F: '/LBR samples parsed \(raw\)/ {gsub(/[^0-9]/, "", $2); print $2; exit}' "${trace}/trace_summary.md")"
    metric="$(jq -r '.qps // .tps // "nan"' "${run}/summary.json")"
    migrations="$(jq -r '.cpu_migrations' "${run}/summary.json")"
    if [[ "${BENCHMARK}" == memcached ]]; then
      tids="$(awk -F, 'NR > 1 && $5 == "ok" {n++} END {print n+0}' "${run}/service_affinity.csv")"
    else
      tids="$(awk -F, 'NR > 1 && $6 == "ok" {n++} END {print n+0}' "${run}/server_affinity.csv")"
    fi
    valid="$(jq -r '.valid' "${run}/summary.json")"
    status=failed
    if [[ "${valid}" == 1 && "${samples:-0}" =~ ^[0-9]+$ && "${samples}" -gt 0 ]]; then
      status=ok
    fi
    printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
      "${rep}" "${attempt}" "${status}" "${samples:-0}" "${metric}" \
      "${migrations}" "${tids}" "${trace}" | tee -a "${OUT}/profiles.csv"
    rm -f "${run}/l2miss_profile.data"
    [[ "${status}" == ok ]] && break
  done
  [[ "${status}" == ok ]] || exit 1
  trace_args+=(--trace-dir "${trace}")
done

python3 "${SUMMARIZER}" --benchmark "${BENCHMARK}" \
  --out-dir "${OUT}/repetition_summary" "${trace_args[@]}"
