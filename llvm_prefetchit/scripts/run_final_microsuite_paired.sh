#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 4 ]]; then
  echo "usage: $0 BENCHMARK BASE_BINARY PREFETCH_BINARY OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
RUNNER="${RUNNER:-${ROOT}/llvm_prefetchit/scripts/run_final_microsuite_variant.sh}"
BENCHMARK="$1"
BASE_BINARY="$(readlink -f "$2")"
PREFETCH_BINARY="$(readlink -f "$3")"
OUT="$(readlink -m "$4")"

REPS="${REPS:-3}"
DURATION="${DURATION:-60}"
PREWARM_DURATION="${PREWARM_DURATION:-0}"
PREWARM_DEPTH="${PREWARM_DEPTH:-32}"
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
EXPECTED_MID_TIDS="${EXPECTED_MID_TIDS:-0}"
REQUIRE_MATCHED_MID_TIDS="${REQUIRE_MATCHED_MID_TIDS:-0}"
DEPTH="${DEPTH:-32}"
PARALLELISM="${PARALLELISM:-4}"
DISPATCH="${DISPATCH:-4}"
RESPONSES="${RESPONSES:-1}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
MAX_PAIR_ATTEMPTS="${MAX_PAIR_ATTEMPTS:-3}"

mkdir -p "${OUT}"
printf 'pair,pair_attempt,position,variant,attempt,qps,l2i_mpki,cpu_migrations,mid_tids,summary_path\n' > "${OUT}/runs.csv"

LAST_RUN_ROW=""
LAST_SUMMARY_PATH=""

run_valid() {
  local pair="$1" pair_attempt="$2" position="$3" variant="$4" binary="$5"
  local run="${OUT}/pair${pair}/attempt${pair_attempt}/${variant}"
  local attempt=0 rc valid
  while ((attempt < MAX_ATTEMPTS)); do
    attempt=$((attempt + 1))
    set +e
    DURATION="${DURATION}" PREWARM_DURATION="${PREWARM_DURATION}" \
      PREWARM_DEPTH="${PREWARM_DEPTH}" \
      MEASURE_SETTLE_DURATION="${MEASURE_SETTLE_DURATION}" \
      GRPC_CORE_CAP="${GRPC_CORE_CAP}" \
      DISABLE_ASLR="${DISABLE_ASLR}" ROUTER_PREPOPULATE="${ROUTER_PREPOPULATE}" \
      ROUTER_LEAF_INSTANCES="${ROUTER_LEAF_INSTANCES}" \
      ROUTER_FIXED_PREWARM_REQUESTS="${ROUTER_FIXED_PREWARM_REQUESTS}" \
      ROUTER_FIXED_PREWARM_TIMEOUT="${ROUTER_FIXED_PREWARM_TIMEOUT}" \
      EVICT_CACHES="${EVICT_CACHES}" \
      EVICT_BYTES_PER_CORE="${EVICT_BYTES_PER_CORE}" EVICT_PASSES="${EVICT_PASSES}" \
      DEPTH="${DEPTH}" PARALLELISM="${PARALLELISM}" DISPATCH="${DISPATCH}" \
      RESPONSES="${RESPONSES}" \
      "${RUNNER}" "${BENCHMARK}" "pair${pair}_try${pair_attempt}_${variant}" \
      "${binary}" "${run}"
    rc="$?"
    set -e
    valid=0
    if ((rc == 0)) && [[ -f "${run}/summary.json" ]]; then
      valid="$(jq -r '.valid' "${run}/summary.json")"
      if ((EXPECTED_MID_TIDS > 0)) && \
        [[ "$(jq -r '.mid_tids' "${run}/summary.json")" -ne "${EXPECTED_MID_TIDS}" ]]; then
        valid=0
      fi
    fi
    if [[ "${valid}" == 1 ]]; then
      LAST_SUMMARY_PATH="${run}/summary.json"
      printf -v LAST_RUN_ROW '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s' \
        "${pair}" "${pair_attempt}" "${position}" "${variant}" "${attempt}" \
        "$(jq -r '.qps' "${run}/summary.json")" \
        "$(jq -r '.l2i_mpki' "${run}/summary.json")" \
        "$(jq -r '.cpu_migrations' "${run}/summary.json")" \
        "$(jq -r '.mid_tids' "${run}/summary.json")" \
        "${run}/summary.json"
      return 0
    fi
  done
  echo "no valid ${variant} run for pair ${pair}" >&2
  return 1
}

for pair in $(seq 1 "${REPS}"); do
  pair_accepted=0
  for pair_attempt in $(seq 1 "${MAX_PAIR_ATTEMPTS}"); do
    baseline_row=""
    prefetch_row=""
    baseline_summary=""
    prefetch_summary=""
    if ((pair % 2 == 1)); then
      if ! run_valid "${pair}" "${pair_attempt}" 1 baseline "${BASE_BINARY}"; then
        continue
      fi
      baseline_row="${LAST_RUN_ROW}"
      baseline_summary="${LAST_SUMMARY_PATH}"
      if ! run_valid "${pair}" "${pair_attempt}" 2 prefetch "${PREFETCH_BINARY}"; then
        continue
      fi
      prefetch_row="${LAST_RUN_ROW}"
      prefetch_summary="${LAST_SUMMARY_PATH}"
    else
      if ! run_valid "${pair}" "${pair_attempt}" 1 prefetch "${PREFETCH_BINARY}"; then
        continue
      fi
      prefetch_row="${LAST_RUN_ROW}"
      prefetch_summary="${LAST_SUMMARY_PATH}"
      if ! run_valid "${pair}" "${pair_attempt}" 2 baseline "${BASE_BINARY}"; then
        continue
      fi
      baseline_row="${LAST_RUN_ROW}"
      baseline_summary="${LAST_SUMMARY_PATH}"
    fi
    baseline_tids="$(jq -r '.mid_tids' "${baseline_summary}")"
    prefetch_tids="$(jq -r '.mid_tids' "${prefetch_summary}")"
    if ((REQUIRE_MATCHED_MID_TIDS == 1)) && \
      [[ "${baseline_tids}" -ne "${prefetch_tids}" ]]; then
      echo "retrying pair ${pair}: baseline_tids=${baseline_tids}, prefetch_tids=${prefetch_tids}, pair_attempt=${pair_attempt}" >&2
      continue
    fi
    printf '%s\n' "${baseline_row}" "${prefetch_row}" | tee -a "${OUT}/runs.csv"
    ln -sfn "attempt${pair_attempt}/baseline" "${OUT}/pair${pair}/baseline"
    ln -sfn "attempt${pair_attempt}/prefetch" "${OUT}/pair${pair}/prefetch"
    pair_accepted=1
    break
  done
  if ((pair_accepted == 0)); then
    echo "no matched valid runs for pair ${pair} after ${MAX_PAIR_ATTEMPTS} pair attempts" >&2
    exit 1
  fi
done

python3 - "${OUT}" "${DURATION}" "${PREWARM_DURATION}" \
  "${MEASURE_SETTLE_DURATION}" "${GRPC_CORE_CAP}" "${EXPECTED_MID_TIDS}" \
  "${REQUIRE_MATCHED_MID_TIDS}" "${DISABLE_ASLR}" "${ROUTER_PREPOPULATE}" \
  "${ROUTER_LEAF_INSTANCES}" "${EVICT_CACHES}" \
  "${ROUTER_FIXED_PREWARM_REQUESTS}" \
  "${ROUTER_FIXED_PREWARM_TIMEOUT}" \
  "${EVICT_BYTES_PER_CORE}" "${EVICT_PASSES}" "${MAX_PAIR_ATTEMPTS}" <<'PY'
import csv
import json
import math
import pathlib
import statistics
import sys

root = pathlib.Path(sys.argv[1])
(
    duration,
    prewarm_duration,
    settle_duration,
    grpc_core_cap,
    expected_mid_tids,
    require_matched_mid_tids,
    disable_aslr,
    router_prepopulate,
    router_leaf_instances,
    evict_caches,
    router_fixed_prewarm_requests,
    router_fixed_prewarm_timeout,
    evict_bytes_per_core,
    evict_passes,
    max_pair_attempts,
) = (
    int(value) for value in sys.argv[2:]
)
rows = list(csv.DictReader((root / "runs.csv").open()))
pairs = {}
for row in rows:
    pairs.setdefault(int(row["pair"]), {})[row["variant"]] = row

pair_rows = []
for pair, variants in sorted(pairs.items()):
    base = variants["baseline"]
    prefetch = variants["prefetch"]
    base_qps = float(base["qps"])
    prefetch_qps = float(prefetch["qps"])
    base_mpki = float(base["l2i_mpki"])
    prefetch_mpki = float(prefetch["l2i_mpki"])
    pair_rows.append(
        {
            "pair": pair,
            "pair_attempt": int(base["pair_attempt"]),
            "baseline_qps": base_qps,
            "prefetch_qps": prefetch_qps,
            "speedup": prefetch_qps / base_qps,
            "baseline_l2i_mpki": base_mpki,
            "prefetch_l2i_mpki": prefetch_mpki,
            "baseline_mid_tids": int(base["mid_tids"]),
            "prefetch_mid_tids": int(prefetch["mid_tids"]),
            "l2i_reduction_pct": 100.0 * (base_mpki - prefetch_mpki) / base_mpki,
        }
    )

with (root / "paired_runs.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=pair_rows[0])
    writer.writeheader()
    writer.writerows(pair_rows)

def stats(values):
    n = len(values)
    stdev = statistics.stdev(values) if n > 1 else 0.0
    return {
        "n": n,
        "mean": statistics.mean(values),
        "stdev": stdev,
        "sem": stdev / math.sqrt(n),
    }

summary = {
    "config": {
        "duration_s": duration,
        "prewarm_duration_s": prewarm_duration,
        "measure_settle_duration_s": settle_duration,
        "grpc_core_cap": grpc_core_cap,
        "expected_mid_tids": expected_mid_tids,
        "require_matched_mid_tids": require_matched_mid_tids,
        "max_pair_attempts": max_pair_attempts,
        "disable_aslr": disable_aslr,
        "router_prepopulate": router_prepopulate,
        "router_leaf_instances": router_leaf_instances,
        "router_fixed_prewarm_requests": router_fixed_prewarm_requests,
        "router_fixed_prewarm_timeout_s": router_fixed_prewarm_timeout,
        "evict_caches": evict_caches,
        "evict_bytes_per_core": evict_bytes_per_core,
        "evict_passes": evict_passes,
    },
    "speedup": stats([row["speedup"] for row in pair_rows]),
    "l2i_reduction_pct": stats([row["l2i_reduction_pct"] for row in pair_rows]),
    "baseline_qps": stats([row["baseline_qps"] for row in pair_rows]),
    "prefetch_qps": stats([row["prefetch_qps"] for row in pair_rows]),
    "baseline_l2i_mpki": stats([row["baseline_l2i_mpki"] for row in pair_rows]),
    "prefetch_l2i_mpki": stats([row["prefetch_l2i_mpki"] for row in pair_rows]),
    "baseline_mid_tids": stats([row["baseline_mid_tids"] for row in pair_rows]),
    "prefetch_mid_tids": stats([row["prefetch_mid_tids"] for row in pair_rows]),
}
(root / "paired_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
PY
