#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/hnpark2/prefetchit"
RUNNER="${ROOT}/llvm_prefetchit/scripts/run_final_memcached_variant.sh"
BASE="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/memcached/base/memcached"
PREFETCH="${ROOT}/llvm_prefetchit/work/datacenter_goal_20260708/memcached/static_allpf/memcached"
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/final_campaign_20260711/memcached_manual_final_rep3}"
REPS="${REPS:-3}"

mkdir -p "${OUT}"
printf 'pair,order,baseline_qps,prefetch_qps,speedup,baseline_mpki,prefetch_mpki,l2i_reduction_pct\n' > "${OUT}/pairs.csv"
for pair in $(seq 1 "${REPS}"); do
  if ((pair % 2 == 1)); then order=(baseline prefetch); else order=(prefetch baseline); fi
  for label in "${order[@]}"; do
    binary="${BASE}"
    [[ "${label}" == prefetch ]] && binary="${PREFETCH}"
    DURATION="${DURATION:-60}" "${RUNNER}" "${label}" "${binary}" "${OUT}/pair${pair}/${label}"
  done
  python3 - "${OUT}" "${pair}" "${order[*]}" <<'PY'
import csv
import json
import sys
from pathlib import Path

out, pair, order = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
baseline = json.loads((out / f"pair{pair}" / "baseline" / "summary.json").read_text())
prefetch = json.loads((out / f"pair{pair}" / "prefetch" / "summary.json").read_text())
row = [
    pair, order, baseline["qps"], prefetch["qps"],
    prefetch["qps"] / baseline["qps"], baseline["l2i_mpki"],
    prefetch["l2i_mpki"],
    100 * (baseline["l2i_mpki"] - prefetch["l2i_mpki"]) / baseline["l2i_mpki"],
]
with (out / "pairs.csv").open("a", newline="") as handle:
    csv.writer(handle).writerow(row)
PY
done

python3 - "${OUT}/pairs.csv" "${OUT}/paired_summary.json" <<'PY'
import csv
import json
import math
import statistics
import sys

rows = list(csv.DictReader(open(sys.argv[1])))

def stats(key):
    data = [float(row[key]) for row in rows]
    stdev = statistics.stdev(data) if len(data) > 1 else 0.0
    return {"mean": statistics.mean(data), "stdev": stdev, "sem": stdev / math.sqrt(len(data))}

result = {
    "pairs": rows,
    "speedup": stats("speedup"),
    "l2i_reduction_pct": stats("l2i_reduction_pct"),
    "baseline_qps": stats("baseline_qps"),
    "prefetch_qps": stats("prefetch_qps"),
    "baseline_mpki": stats("baseline_mpki"),
    "prefetch_mpki": stats("prefetch_mpki"),
}
open(sys.argv[2], "w").write(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
PY
