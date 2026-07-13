#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit/llvm_prefetchit"
RUNNER="${ROOT}/scripts/run_final_memcached_variant.sh"
BIN_DIR="${BIN_DIR:-${ROOT}/work/data_prefetch_reexperiment_20260712/memcached_variants/bins}"
OUT="${1:-${ROOT}/results/data_prefetch_reexperiment_20260712/memcached_variant_screen}"
DURATION="${DURATION:-12}"
WARMUP_DURATION="${WARMUP_DURATION:-5}"
CLIENT_THREADS="${CLIENT_THREADS:-8}"
CONNECTIONS_PER_THREAD="${CONNECTIONS_PER_THREAD:-100}"
SERVICE_THREADS="${SERVICE_THREADS:-8}"
KEY_MAX="${KEY_MAX:-100000}"
PORT_BASE="${PORT_BASE:-11340}"
PROTOCOL="${PROTOCOL:-memcache_text}"
PIPELINE="${PIPELINE:-1}"
DATA_SIZE="${DATA_SIZE:-64}"
READ_WRITE_RATIO="${READ_WRITE_RATIO:-0:1}"
KEY_PATTERN="${KEY_PATTERN:-R:R}"
HASHPOWER="${HASHPOWER:-0}"
NO_HASH_EXPAND="${NO_HASH_EXPAND:-0}"

variants=(
  baseline get_late get_early get_early_next item_early
  baseline doitem_early assoc_early get_item_early get_item_early_next
  baseline get_item_do_early get_item_do_early_next
  get_item_do_assoc_early get_item_do_assoc_early_next
  baseline get_item_do_assoc_early_l2 get_item_do_assoc_early_l1
  get_item_do_assoc_early_nta get_item_do_assoc_resp_early
  all_early all_early_next baseline
)
if [[ -n "${VARIANTS:-}" ]]; then
  read -r -a variants <<< "${VARIANTS}"
fi

mkdir -p "${OUT}"
for i in "${!variants[@]}"; do
  variant="${variants[$i]}"
  label="$(printf '%02d_%s' "$((i + 1))" "${variant}")"
  DURATION="${DURATION}" WARMUP_DURATION="${WARMUP_DURATION}" \
    CLIENT_THREADS="${CLIENT_THREADS}" \
    CONNECTIONS_PER_THREAD="${CONNECTIONS_PER_THREAD}" \
    SERVICE_THREADS="${SERVICE_THREADS}" KEY_MAX="${KEY_MAX}" \
    PROTOCOL="${PROTOCOL}" PIPELINE="${PIPELINE}" DATA_SIZE="${DATA_SIZE}" \
    READ_WRITE_RATIO="${READ_WRITE_RATIO}" KEY_PATTERN="${KEY_PATTERN}" \
    HASHPOWER="${HASHPOWER}" NO_HASH_EXPAND="${NO_HASH_EXPAND}" \
    PORT="$((PORT_BASE + i))" \
    "${RUNNER}" "${label}" "${BIN_DIR}/memcached.${variant}" "${OUT}/${label}"
done

python3 - "${OUT}" <<'PY'
import csv
import json
import pathlib
import statistics
import sys

root = pathlib.Path(sys.argv[1])
rows = [json.loads(path.read_text()) for path in sorted(root.glob("*/summary.json"))]
baselines = [row["qps"] for row in rows if row["label"].endswith("_baseline")]
baseline_qps = statistics.mean(baselines)
for row in rows:
    row["speedup_vs_baseline_mean"] = row["qps"] / baseline_qps

fields = [
    "label", "qps", "speedup_vs_baseline_mean", "l2i_mpki", "ipc",
    "cpu_migrations", "valid", "binary",
]
with (root / "screen_summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

for row in sorted(rows, key=lambda item: item["speedup_vs_baseline_mean"], reverse=True):
    print(
        f"{row['label']},{row['qps']:.2f},"
        f"{row['speedup_vs_baseline_mean']:.6f},"
        f"{row['l2i_mpki']:.6f},{row['cpu_migrations']},{row['valid']}"
    )
PY
