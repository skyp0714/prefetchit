#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 2 ]]; then
  echo "usage: $0 router|setalgebra|hdsearch OUT_DIR" >&2
  exit 2
fi

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BENCHMARK="$1"
OUT="$(readlink -m "$2")"
RUNNER="${ROOT}/scripts/run_final_microsuite_variant.sh"
BIN_DIR="${BIN_DIR:-${ROOT}/work/data_prefetch_reexperiment_20260712/microsuite_handoff/${BENCHMARK}}"
DURATION="${DURATION:-12}"
PREWARM_DURATION="${PREWARM_DURATION:-10}"
PREWARM_DEPTH="${PREWARM_DEPTH:-32}"
MEASURE_SETTLE_DURATION="${MEASURE_SETTLE_DURATION:-0}"
GRPC_CORE_CAP="${GRPC_CORE_CAP:-6}"
DEPTH="${DEPTH:-32}"
PARALLELISM="${PARALLELISM:-2}"
DISPATCH="${DISPATCH:-2}"
RESPONSES="${RESPONSES:-1}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"

variants=(
  baseline producer_tag1 producer_tag2 producer_tag4 producer_tag8
  baseline producer_code1 producer_code2 producer_code4 producer_code8
  baseline producer_tag1_code1 producer_tag2_code2 producer_tag4_code2
  producer_tag4_code4 baseline consumer_tag1_code1 consumer_tag2_code2
  consumer_tag4_code4 both_tag1_code1 both_tag2_code2 both_tag4_code4
  baseline producer_tag2_code2_l2 producer_tag2_code2_l1
  producer_tag2_code2_nta baseline
)
if [[ -n "${VARIANTS:-}" ]]; then
  read -r -a variants <<< "${VARIANTS}"
fi

mkdir -p "${OUT}"
for i in "${!variants[@]}"; do
  variant="${variants[$i]}"
  label="$(printf '%02d_%s' "$((i + 1))" "${variant}")"
  valid=0
  for attempt in $(seq 1 "${MAX_ATTEMPTS}"); do
    set +e
    DURATION="${DURATION}" PREWARM_DURATION="${PREWARM_DURATION}" \
      PREWARM_DEPTH="${PREWARM_DEPTH}" GRPC_CORE_CAP="${GRPC_CORE_CAP}" \
      MEASURE_SETTLE_DURATION="${MEASURE_SETTLE_DURATION}" \
      DEPTH="${DEPTH}" PARALLELISM="${PARALLELISM}" DISPATCH="${DISPATCH}" \
      RESPONSES="${RESPONSES}" \
      "${RUNNER}" "${BENCHMARK}" "${label}" \
      "${BIN_DIR}/mid_tier_server.${variant}" "${OUT}/${label}"
    rc="$?"
    set -e
    if ((rc == 0)) && [[ -f "${OUT}/${label}/summary.json" ]]; then
      valid="$(jq -r '.valid' "${OUT}/${label}/summary.json")"
    fi
    [[ "${valid}" == 1 ]] && break
  done
  [[ "${valid}" == 1 ]] || {
    echo "no valid run for ${label} after ${MAX_ATTEMPTS} attempts" >&2
    exit 1
  }
done

python3 - "${OUT}" <<'PY'
import csv
import json
import pathlib
import statistics
import sys

root = pathlib.Path(sys.argv[1])
rows = [json.loads(path.read_text()) for path in sorted(root.glob("*/summary.json"))]
baseline_qps = statistics.mean(
    row["qps"] for row in rows if row["label"].endswith("_baseline")
)
for row in rows:
    row["speedup_vs_baseline_mean"] = row["qps"] / baseline_qps
fields = [
    "label", "qps", "speedup_vs_baseline_mean", "l2i_mpki", "ipc",
    "failed_responses", "cpu_migrations", "valid", "binary",
]
with (root / "screen_summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
for row in sorted(rows, key=lambda item: item["speedup_vs_baseline_mean"], reverse=True):
    print(
        f"{row['label']},{row['qps']:.2f},"
        f"{row['speedup_vs_baseline_mean']:.6f},{row['l2i_mpki']:.6f},"
        f"{row['failed_responses']},{row['cpu_migrations']},{row['valid']}"
    )
PY
