#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 4 ]]; then
  echo "usage: $0 BENCHMARK BASE_BINARY PREFETCH_BINARY OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
RUNNER="${ROOT}/llvm_prefetchit/scripts/run_final_microsuite_variant.sh"
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
EXPECTED_MID_TIDS="${EXPECTED_MID_TIDS:-0}"
REQUIRE_MATCHED_MID_TIDS="${REQUIRE_MATCHED_MID_TIDS:-0}"
DEPTH="${DEPTH:-32}"
PARALLELISM="${PARALLELISM:-4}"
DISPATCH="${DISPATCH:-4}"
RESPONSES="${RESPONSES:-1}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"

mkdir -p "${OUT}"
printf 'pair,position,variant,attempt,qps,l2i_mpki,cpu_migrations,mid_tids,summary_path\n' > "${OUT}/runs.csv"

run_valid() {
  local pair="$1" position="$2" variant="$3" binary="$4"
  local run="${OUT}/pair${pair}/${variant}"
  local attempt=0 rc valid
  while ((attempt < MAX_ATTEMPTS)); do
    attempt=$((attempt + 1))
    set +e
    DURATION="${DURATION}" PREWARM_DURATION="${PREWARM_DURATION}" \
      PREWARM_DEPTH="${PREWARM_DEPTH}" \
      MEASURE_SETTLE_DURATION="${MEASURE_SETTLE_DURATION}" \
      GRPC_CORE_CAP="${GRPC_CORE_CAP}" \
      DEPTH="${DEPTH}" PARALLELISM="${PARALLELISM}" DISPATCH="${DISPATCH}" \
      RESPONSES="${RESPONSES}" \
      "${RUNNER}" "${BENCHMARK}" "pair${pair}_${variant}" "${binary}" "${run}"
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
      printf '%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "${pair}" "${position}" "${variant}" "${attempt}" \
        "$(jq -r '.qps' "${run}/summary.json")" \
        "$(jq -r '.l2i_mpki' "${run}/summary.json")" \
        "$(jq -r '.cpu_migrations' "${run}/summary.json")" \
        "$(jq -r '.mid_tids' "${run}/summary.json")" \
        "${run}/summary.json" | tee -a "${OUT}/runs.csv"
      return 0
    fi
  done
  echo "no valid ${variant} run for pair ${pair}" >&2
  return 1
}

for pair in $(seq 1 "${REPS}"); do
  if ((pair % 2 == 1)); then
    run_valid "${pair}" 1 baseline "${BASE_BINARY}"
    run_valid "${pair}" 2 prefetch "${PREFETCH_BINARY}"
  else
    run_valid "${pair}" 1 prefetch "${PREFETCH_BINARY}"
    run_valid "${pair}" 2 baseline "${BASE_BINARY}"
  fi
  baseline_tids="$(jq -r '.mid_tids' "${OUT}/pair${pair}/baseline/summary.json")"
  prefetch_tids="$(jq -r '.mid_tids' "${OUT}/pair${pair}/prefetch/summary.json")"
  if ((REQUIRE_MATCHED_MID_TIDS == 1)) && \
    [[ "${baseline_tids}" -ne "${prefetch_tids}" ]]; then
    echo "mid-tier worker population changed in pair ${pair}: baseline=${baseline_tids}, prefetch=${prefetch_tids}" >&2
    exit 1
  fi
done

python3 - "${OUT}" "${DURATION}" "${PREWARM_DURATION}" \
  "${MEASURE_SETTLE_DURATION}" "${GRPC_CORE_CAP}" "${EXPECTED_MID_TIDS}" \
  "${REQUIRE_MATCHED_MID_TIDS}" <<'PY'
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
