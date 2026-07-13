#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 PREFETCH_POSTGRES OUT_DIR LABEL" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit/llvm_prefetchit"
RUNNER="${ROOT}/scripts/run_final_postgresql_variant.sh"
BASE="${POSTGRES_BASE:-${ROOT}/work/datacenter_goal_20260708/postgres/install_base/bin/postgres}"
PREFETCH="$(readlink -f "$1")"
OUT="$(readlink -m "$2")"
LABEL="$3"
REPS="${REPS:-5}"
DURATION="${DURATION:-30}"
CLIENTS="${CLIENTS:-8}"
CLIENT_THREADS="${CLIENT_THREADS:-${CLIENTS}}"
QUERY_MODE="${QUERY_MODE:-prepared}"
PORT_BASE="${PORT_BASE:-55640}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"

mkdir -p "${OUT}"
printf 'pair,position,variant,attempt,tps,l2i_mpki,cpu_migrations,summary_path\n' \
  > "${OUT}/runs.csv"

run_valid() {
  local pair="$1" position="$2" variant="$3" binary="$4"
  local attempt=0 run rc valid port
  run="${OUT}/pair${pair}/${variant}"
  port="$((PORT_BASE + pair * 2 + position))"
  while ((attempt < MAX_ATTEMPTS)); do
    attempt=$((attempt + 1))
    set +e
    DURATION="${DURATION}" CLIENTS="${CLIENTS}" CLIENT_THREADS="${CLIENT_THREADS}" \
      QUERY_MODE="${QUERY_MODE}" PORT="${port}" \
      "${RUNNER}" "${LABEL}_pair${pair}_${variant}" "${binary}" "${run}"
    rc="$?"
    set -e
    valid=0
    if ((rc == 0)) && [[ -f "${run}/summary.json" ]]; then
      valid="$(jq -r '.valid' "${run}/summary.json")"
    fi
    if [[ "${valid}" == 1 ]]; then
      printf '%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "${pair}" "${position}" "${variant}" "${attempt}" \
        "$(jq -r '.tps' "${run}/summary.json")" \
        "$(jq -r '.l2i_mpki' "${run}/summary.json")" \
        "$(jq -r '.cpu_migrations' "${run}/summary.json")" \
        "${run}/summary.json" | tee -a "${OUT}/runs.csv"
      return 0
    fi
  done
  echo "no valid ${variant} run for pair ${pair}" >&2
  return 1
}

for pair in $(seq 1 "${REPS}"); do
  if ((pair % 2 == 1)); then
    run_valid "${pair}" 1 baseline "${BASE}"
    run_valid "${pair}" 2 prefetch "${PREFETCH}"
  else
    run_valid "${pair}" 1 prefetch "${PREFETCH}"
    run_valid "${pair}" 2 baseline "${BASE}"
  fi
done

python3 - "${OUT}" "${LABEL}" "${DURATION}" "${CLIENTS}" \
  "${CLIENT_THREADS}" "${QUERY_MODE}" <<'PY'
import csv
import json
import math
import pathlib
import statistics
import sys

root = pathlib.Path(sys.argv[1])
label = sys.argv[2]
duration, clients, client_threads = map(int, sys.argv[3:6])
query_mode = sys.argv[6]
rows = list(csv.DictReader((root / "runs.csv").open()))
pairs = {}
for row in rows:
    pairs.setdefault(int(row["pair"]), {})[row["variant"]] = row

pair_rows = []
for pair, variants in sorted(pairs.items()):
    baseline = variants["baseline"]
    prefetch = variants["prefetch"]
    base_tps = float(baseline["tps"])
    pf_tps = float(prefetch["tps"])
    base_mpki = float(baseline["l2i_mpki"])
    pf_mpki = float(prefetch["l2i_mpki"])
    pair_rows.append({
        "pair": pair,
        "baseline_tps": base_tps,
        "prefetch_tps": pf_tps,
        "speedup": pf_tps / base_tps,
        "baseline_l2i_mpki": base_mpki,
        "prefetch_l2i_mpki": pf_mpki,
        "l2i_reduction_pct": 100.0 * (base_mpki - pf_mpki) / base_mpki,
    })

with (root / "paired_runs.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=pair_rows[0])
    writer.writeheader()
    writer.writerows(pair_rows)

def stats(values):
    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "stdev": stdev,
        "sem": stdev / math.sqrt(len(values)),
    }

summary = {
    "label": label,
    "config": {
        "duration_s": duration,
        "clients": clients,
        "client_threads": client_threads,
        "query_mode": query_mode,
    },
    "speedup": stats([row["speedup"] for row in pair_rows]),
    "l2i_reduction_pct": stats([row["l2i_reduction_pct"] for row in pair_rows]),
    "baseline_tps": stats([row["baseline_tps"] for row in pair_rows]),
    "prefetch_tps": stats([row["prefetch_tps"] for row in pair_rows]),
    "baseline_l2i_mpki": stats([row["baseline_l2i_mpki"] for row in pair_rows]),
    "prefetch_l2i_mpki": stats([row["prefetch_l2i_mpki"] for row in pair_rows]),
}
(root / "paired_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
PY
