#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 VARIANT_INSTALLS_DIR OUT_DIR" >&2
  exit 2
fi

ROOT="${LLVM_PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUNNER="${ROOT}/scripts/run_final_postgresql_variant.sh"
BASE="${POSTGRES_BASE:-${ROOT}/work/datacenter_goal_20260708/postgres/install_base/bin/postgres}"
INSTALLS="$(readlink -f "$1")"
OUT="$(readlink -m "$2")"
DURATION="${DURATION:-20}"
CLIENTS="${CLIENTS:-8}"
CLIENT_THREADS="${CLIENT_THREADS:-${CLIENTS}}"
QUERY_MODE="${QUERY_MODE:-prepared}"
PORT_BASE="${PORT_BASE:-55540}"
VARIANTS="${VARIANTS:-baseline cov25_d1_32_b4_o0 cov50_d1_32_b4_o0 baseline cov75_d1_32_b4_o0 cov100_d1_32_b4_o0 cov100_d1_32_b4_o064 cov100_d1_8_b16_o0 baseline}"

read -r -a variants <<< "${VARIANTS}"
mkdir -p "${OUT}"
for i in "${!variants[@]}"; do
  variant="${variants[$i]}"
  label="$(printf '%02d_%s' "$((i + 1))" "${variant}")"
  binary="${INSTALLS}/${variant}/bin/postgres"
  if [[ "${variant}" == baseline ]]; then
    binary="${BASE}"
  fi
  DURATION="${DURATION}" CLIENTS="${CLIENTS}" CLIENT_THREADS="${CLIENT_THREADS}" \
    QUERY_MODE="${QUERY_MODE}" PORT="$((PORT_BASE + i))" \
    "${RUNNER}" "${label}" "${binary}" "${OUT}/${label}"
done

python3 - "${OUT}" <<'PY'
import csv
import json
import pathlib
import statistics
import sys

root = pathlib.Path(sys.argv[1])
rows = [json.loads(path.read_text()) for path in sorted(root.glob("*/summary.json"))]
baselines = [row["tps"] for row in rows if row["label"].endswith("_baseline")]
baseline_tps = statistics.mean(baselines)
for row in rows:
    row["speedup_vs_baseline_mean"] = row["tps"] / baseline_tps

fields = [
    "label", "tps", "speedup_vs_baseline_mean", "l2i_mpki", "ipc",
    "cpu_migrations", "pinner_corrections", "valid", "binary",
]
with (root / "screen_summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

for row in sorted(rows, key=lambda item: item["speedup_vs_baseline_mean"], reverse=True):
    print(
        f"{row['label']},{row['tps']:.2f},"
        f"{row['speedup_vs_baseline_mean']:.6f},"
        f"{row['l2i_mpki']:.6f},{row['cpu_migrations']},{row['valid']}"
    )
PY
