#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"

RUN_ID="${RUN_ID:-best_neighbor_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetch_best_sweep/${RUN_ID}}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-3}"
AUTOTUNE_HOURS="${AUTOTUNE_HOURS:-10}"
BUILD_JOBS="${BUILD_JOBS:-32}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
BEST_PLAN="${BEST_PLAN:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/plateau_fixed_20260604_013311/batch_repair/runs/v02_cov50_tops_d4_24_b8_o2/plan/prefetcht1.plan.json}"
VARIANTS_FILE="${OUT_DIR}/best_neighbor_variants.txt"
LOG="${OUT_DIR}/best_neighbor_sweep.log"

mkdir -p "${OUT_DIR}"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[err] missing file: ${path}" | tee -a "${LOG}" >&2
    exit 1
  fi
}

require_dir() {
  local path="$1"
  if [[ ! -d "${path}" ]]; then
    echo "[err] missing directory: ${path}" | tee -a "${LOG}" >&2
    exit 1
  fi
}

trace_inputs_from_plan() {
  python3 - "$1" <<'PY'
import json
import sys

plan = json.load(open(sys.argv[1], encoding="utf-8"))
trace_dirs = plan.get("trace_dirs") or plan.get("trace_inputs") or []
if isinstance(trace_dirs, str):
    trace_dirs = [item for item in trace_dirs.split(":") if item]
print(":".join(trace_dirs))
PY
}

write_variants() {
  cat > "${VARIANTS_FILE}" <<'EOF'
# name|top_k|depth_min|depth|site_budget|selection_mode|sites_per_depth|candidate_pool|target_coverage_pct|prefetch_byte_offsets|branch_depth_policy
# Local sweep around the best runtime variant:
#   cov50_tops_d4_24_b8_o2, offsets 0/64, prefetcht1.
# Keep the search bounded. Prior high-coverage/all-path/per-depth variants
# inflated instruction footprint and regressed runtime.
cov45_tops_d4_24_b8_o2|999999|4|24|8|top-sites|1|0|45|0,64|
cov48_tops_d4_24_b8_o2|999999|4|24|8|top-sites|1|0|48|0,64|
cov50_tops_d4_24_b8_o2|999999|4|24|8|top-sites|1|0|50|0,64|
cov52_tops_d4_24_b8_o2|999999|4|24|8|top-sites|1|0|52|0,64|
cov55_tops_d4_24_b8_o2|999999|4|24|8|top-sites|1|0|55|0,64|
cov50_tops_d4_24_b4_o2|999999|4|24|4|top-sites|1|0|50|0,64|
cov50_tops_d4_24_b6_o2|999999|4|24|6|top-sites|1|0|50|0,64|
cov50_tops_d4_24_b10_o2|999999|4|24|10|top-sites|1|0|50|0,64|
cov50_tops_d4_24_b12_o2|999999|4|24|12|top-sites|1|0|50|0,64|
cov50_tops_d4_20_b8_o2|999999|4|20|8|top-sites|1|0|50|0,64|
cov50_tops_d4_22_b8_o2|999999|4|22|8|top-sites|1|0|50|0,64|
cov50_tops_d4_26_b8_o2|999999|4|26|8|top-sites|1|0|50|0,64|
cov50_tops_d4_28_b8_o2|999999|4|28|8|top-sites|1|0|50|0,64|
cov50_tops_d2_24_b8_o2|999999|2|24|8|top-sites|1|0|50|0,64|
cov50_tops_d3_24_b8_o2|999999|3|24|8|top-sites|1|0|50|0,64|
cov50_tops_d5_24_b8_o2|999999|5|24|8|top-sites|1|0|50|0,64|
cov50_tops_d6_24_b8_o2|999999|6|24|8|top-sites|1|0|50|0,64|
cov50_tops_d4_24_b8_o1|999999|4|24|8|top-sites|1|0|50|0|
cov50_tops_d4_24_b8_o3|999999|4|24|8|top-sites|1|0|50|0,64,128|
EOF
}

write_runtime_leaderboard() {
  local aggregate="${OUT_DIR}/prefetcht1_screen/aggregate.csv"
  local leaderboard="${OUT_DIR}/runtime_leaderboard.md"
  local best_file="${OUT_DIR}/best_runtime_variant.txt"
  if [[ ! -f "${aggregate}" ]]; then
    log "skip runtime leaderboard: missing ${aggregate}"
    return 0
  fi
  python3 - "${aggregate}" "${leaderboard}" "${best_file}" <<'PY'
import csv
import math
import sys
from pathlib import Path

aggregate, leaderboard, best_file = map(Path, sys.argv[1:4])

def num(row, key):
    try:
        return float(row.get(key, "nan"))
    except ValueError:
        return float("nan")

rows = []
with aggregate.open(newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row.get("status") != "ok":
            continue
        elapsed = num(row, "elapsed_delta_pct")
        if math.isfinite(elapsed):
            rows.append(row)

rows.sort(key=lambda r: (num(r, "elapsed_delta_pct"), num(r, "l2i_mpki_delta_pct")))

lines = [
    "# Runtime Leaderboard",
    "",
    "| Rank | Variant | Runtime s | Runtime Delta % | L2I MPKI | L2I Delta % | Instructions Delta % | Injected | Planned |",
    "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
]
for idx, row in enumerate(rows, 1):
    lines.append(
        "| "
        f"{idx} | `{row.get('variant','')}` | "
        f"{num(row, 'elapsed_sec'):.3f} | "
        f"{num(row, 'elapsed_delta_pct'):+.3f} | "
        f"{num(row, 'l2i_mpki'):.6f} | "
        f"{num(row, 'l2i_mpki_delta_pct'):+.3f} | "
        f"{num(row, 'instructions_delta_pct'):+.3f} | "
        f"{row.get('pass_injected','')} | "
        f"{row.get('planned_injections','')} |"
    )

if rows:
    best = rows[0]
    best_file.write_text(
        "\n".join(
            [
                best.get("variant", ""),
                best.get("run_dir", ""),
                best.get("binary", ""),
                best.get("elapsed_delta_pct", ""),
                best.get("l2i_mpki_delta_pct", ""),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    lines += [
        "",
        "## Best Runtime",
        "",
        f"- Variant: `{best.get('variant','')}`",
        f"- Runtime delta: {num(best, 'elapsed_delta_pct'):+.3f}%",
        f"- L2I MPKI delta: {num(best, 'l2i_mpki_delta_pct'):+.3f}%",
        f"- Binary: `{best.get('binary','')}`",
    ]
else:
    lines.append("")
    lines.append("No successful variants yet.")

leaderboard.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  log "runtime leaderboard: ${leaderboard}"
}

require_file "${BASELINE_BINARY}"
require_file "${BASELINE_SUMMARY}"
require_file "${BEST_PLAN}"
require_dir "${SOURCE_WORK}"
require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh"

TRACE_INPUTS="${TRACE_INPUTS:-$(trace_inputs_from_plan "${BEST_PLAN}")}"
if [[ -z "${TRACE_INPUTS}" ]]; then
  echo "[err] could not derive TRACE_INPUTS from ${BEST_PLAN}" | tee -a "${LOG}" >&2
  exit 1
fi
IFS=':' read -r -a trace_dirs <<< "${TRACE_INPUTS}"
for trace_dir in "${trace_dirs[@]}"; do
  [[ -n "${trace_dir}" ]] || continue
  require_dir "${trace_dir}"
  require_file "${trace_dir}/lbr_symbolic_dump.txt"
done

write_variants
cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
best_plan=${BEST_PLAN}
trace_inputs=${TRACE_INPUTS}
trace_input_count=${#trace_dirs[@]}
baseline_binary=${BASELINE_BINARY}
baseline_summary=${BASELINE_SUMMARY}
source_work=${SOURCE_WORK}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
screen_iterations=${SCREEN_ITERATIONS}
autotune_hours=${AUTOTUNE_HOURS}
build_jobs=${BUILD_JOBS}
prefetch_mnemonic=prefetcht1
EOF

log "best-neighbor prefetcht1 sweep start: ${OUT_DIR}"
log "trace input count: ${#trace_dirs[@]}"
log "profile iterations per variant: ${SCREEN_ITERATIONS}"
log "variants: ${VARIANTS_FILE}"

set +e
RUN_ID="prefetcht1_screen" \
OUT_DIR="${OUT_DIR}/prefetcht1_screen" \
VARIANTS_FILE="${VARIANTS_FILE}" \
TRACE_INPUTS="${TRACE_INPUTS}" \
TRACE_INPUT="${TRACE_INPUTS%%:*}" \
BASELINE_BINARY="${BASELINE_BINARY}" \
BASELINE_SUMMARY="${BASELINE_SUMMARY}" \
SOURCE_WORK="${SOURCE_WORK}" \
AUTOTUNE_HOURS="${AUTOTUNE_HOURS}" \
SCREEN_ITERATIONS="${SCREEN_ITERATIONS}" \
SCREEN_RUN_TRACE=0 \
RUN_CONFIRMATION=0 \
PREFETCH_MNEMONIC=prefetcht1 \
PREFETCH_LABEL=prefetcht1 \
BUILD_JOBS="${BUILD_JOBS}" \
PROFILE_CORE="${PROFILE_CORE}" \
MAX_CYCLES="${MAX_CYCLES}" \
ALLOW_UNRESOLVED_TARGETS=1 \
STOP_RUNTIME_DELTA_PCT= \
OBJDUMP_BIN=llvm-objdump-19 \
ADDR2LINE_BIN=llvm-addr2line-19 \
bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh" 2>&1 | tee -a "${LOG}"
rc=${PIPESTATUS[0]}
set -e

write_runtime_leaderboard
log "best-neighbor prefetcht1 sweep done: rc=${rc}"
exit "${rc}"
