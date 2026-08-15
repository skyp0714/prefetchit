#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

AUTOTUNE_HOURS="${AUTOTUNE_HOURS:-8}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetcht1_autotune/${RUN_ID}}"
RUNS_DIR="${OUT_DIR}/runs"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
CONFIRM_ITERATIONS="${CONFIRM_ITERATIONS:-3}"
TRACE_DURATION_SEC="${TRACE_DURATION_SEC:-20}"
TRACE_SAMPLE_PERIOD="${TRACE_SAMPLE_PERIOD:-100000}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
SCREEN_RUN_TRACE="${SCREEN_RUN_TRACE:-0}"
RUN_CONFIRMATION="${RUN_CONFIRMATION:-1}"
STOP_RUNTIME_DELTA_PCT="${STOP_RUNTIME_DELTA_PCT:-}"
STOP_L2I_DELTA_PCT="${STOP_L2I_DELTA_PCT:-}"
EARLY_STOP_WORSE_STREAK="${EARLY_STOP_WORSE_STREAK:-0}"
EARLY_STOP_WORSE_MARGIN_PCT="${EARLY_STOP_WORSE_MARGIN_PCT:-1.0}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS:-0}"
BRANCH_DEPTH_POLICY="${BRANCH_DEPTH_POLICY:-}"
PREFETCH_LABEL="${PREFETCH_LABEL:-${PREFETCH_MNEMONIC}}"
SUMMARY_RANK_BY="${SUMMARY_RANK_BY:-l2i}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
TRACE_INPUT="${TRACE_INPUT:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/trace_l2i_code_rd_miss_precise/baseline_qsort_${MAX_CYCLES}/l2_miss}"
TRACE_INPUTS="${TRACE_INPUTS:-${TRACE_INPUT}}"
TARGET_COVERAGE_PCT="${TARGET_COVERAGE_PCT:-0}"
ALLOW_UNRESOLVED_TARGETS="${ALLOW_UNRESOLVED_TARGETS:-0}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
EVAL_SCRIPT="${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh"
SUMMARY_TOOL="${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py"
VARIANTS_FILE="${VARIANTS_FILE:-}"
LOG="${OUT_DIR}/autotune.log"

mkdir -p "${OUT_DIR}" "${RUNS_DIR}"

START_EPOCH="$(date +%s)"
DEADLINE_EPOCH="$((START_EPOCH + AUTOTUNE_HOURS * 3600))"

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

require_trace_inputs() {
  local trace_dir
  local found=0
  IFS=':' read -r -a _trace_dirs <<< "${TRACE_INPUTS}"
  for trace_dir in "${_trace_dirs[@]}"; do
    [[ -n "${trace_dir}" ]] || continue
    found=1
    require_dir "${trace_dir}"
    require_file "${trace_dir}/lbr_symbolic_dump.txt"
  done
  if [[ "${found}" -eq 0 ]]; then
    echo "[err] TRACE_INPUTS did not contain any trace directories" | tee -a "${LOG}" >&2
    exit 1
  fi
}

seconds_left() {
  echo $((DEADLINE_EPOCH - $(date +%s)))
}

prune_autotune_workdirs() {
  find "${RUNS_DIR}" -mindepth 2 -maxdepth 2 -type d -name work -prune -exec rm -rf {} + 2>/dev/null || true
}

append_failure() {
  local variant="$1"
  local run_dir="$2"
  local note="$3"
  python3 "${SUMMARY_TOOL}" \
    --autotune-dir "${OUT_DIR}" \
    --variant "${variant}" \
    --run-dir "${run_dir}" \
    --baseline-summary "${BASELINE_SUMMARY}" \
    --max-cycles "${MAX_CYCLES}" \
    --status fail \
    --prefetch-label "${PREFETCH_LABEL}" \
    --rank-by "${SUMMARY_RANK_BY}" \
    --note "${note}" || true
}

run_variant() {
  local index="$1"
  shift
  local name="$1"
  shift
  local top_k="$1"
  shift
  local depth_min="$1"
  shift
  local depth="$1"
  shift
  local budget="$1"
  shift
  local mode="$1"
  shift
  local sites_per_depth="$1"
  shift
  local candidate_pool="$1"
  shift
  local target_coverage_pct="${1:-${TARGET_COVERAGE_PCT}}"
  shift || true
  local prefetch_byte_offsets="${1:-${PREFETCH_BYTE_OFFSETS}}"
  shift || true
  local branch_depth_policy="${1:-${BRANCH_DEPTH_POLICY}}"

  local left
  left="$(seconds_left)"
  if (( left <= 0 )); then
    log "deadline reached before ${name}; stopping variant launch"
    return 1
  fi

  local run_id
  run_id="$(printf 'v%02d_%s' "${index}" "${name}")"
  local run_dir="${RUNS_DIR}/${run_id}"

  log "variant ${run_id}: top_k=${top_k} target_cov=${target_coverage_pct}% d=${depth_min}-${depth} budget=${budget} mode=${mode} spd=${sites_per_depth} pool=${candidate_pool} offsets=${prefetch_byte_offsets} branch_policy=${branch_depth_policy:-default} seconds_left=${left}"
  prune_autotune_workdirs

  set +e
  RESULT_BASE="${RUNS_DIR}" \
  RUN_ID="${run_id}" \
  TRACE_INPUT="${TRACE_INPUT}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  BASELINE_BINARY="${BASELINE_BINARY}" \
  SOURCE_WORK="${SOURCE_WORK}" \
  CONFIG="${CONFIG}" \
  TOP_K="${top_k}" \
  TARGET_COVERAGE_PCT="${target_coverage_pct}" \
  DEPTH_MIN="${depth_min}" \
  DEPTH="${depth}" \
  SITE_BUDGET="${budget}" \
  CANDIDATE_POOL="${candidate_pool}" \
  SELECTION_MODE="${mode}" \
  SITES_PER_DEPTH="${sites_per_depth}" \
  ALLOW_UNRESOLVED_TARGETS="${ALLOW_UNRESOLVED_TARGETS}" \
  PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC}" \
  PREFETCH_BYTE_OFFSETS="${prefetch_byte_offsets}" \
  BRANCH_DEPTH_POLICY="${branch_depth_policy}" \
  PREFETCH_LABEL="${PREFETCH_LABEL}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  PROFILE_ITERATIONS="${SCREEN_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  TRACE_DURATION_SEC="${TRACE_DURATION_SEC}" \
  TRACE_SAMPLE_PERIOD="${TRACE_SAMPLE_PERIOD}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  OBJDUMP_BIN="${OBJDUMP_BIN:-objdump}" \
  ADDR2LINE_BIN="${ADDR2LINE_BIN:-llvm-addr2line-19}" \
  RUN_BASELINE=0 \
  RUN_TRACE="${SCREEN_RUN_TRACE}" \
  CLEAN_WORKDIR=1 \
  bash "${EVAL_SCRIPT}" > "${run_dir}.driver.log" 2>&1
  local rc=$?
  set -e

  if [[ "${rc}" -ne 0 ]]; then
    log "variant ${run_id} failed rc=${rc}; see ${run_dir}.driver.log"
    append_failure "${run_id}" "${run_dir}" "eval_rc=${rc}"
    prune_autotune_workdirs
    return 0
  fi

  python3 "${SUMMARY_TOOL}" \
    --autotune-dir "${OUT_DIR}" \
    --variant "${run_id}" \
    --run-dir "${run_dir}" \
    --baseline-summary "${BASELINE_SUMMARY}" \
    --max-cycles "${MAX_CYCLES}" \
    --status ok \
    --prefetch-label "${PREFETCH_LABEL}" \
    --rank-by "${SUMMARY_RANK_BY}"

  prune_autotune_workdirs
  if [[ -f "${OUT_DIR}/leaderboard.md" ]]; then
    sed -n '1,18p' "${OUT_DIR}/leaderboard.md" | tee -a "${LOG}"
  fi
  if [[ -n "${STOP_RUNTIME_DELTA_PCT}" || -n "${STOP_L2I_DELTA_PCT}" ]]; then
    if python3 - "${OUT_DIR}/aggregate.csv" "${run_id}" "${STOP_RUNTIME_DELTA_PCT}" "${STOP_L2I_DELTA_PCT}" <<'PY'
import csv
import math
import sys

aggregate, variant, runtime_threshold, l2i_threshold = sys.argv[1:5]
runtime_threshold = float(runtime_threshold) if runtime_threshold else None
l2i_threshold = float(l2i_threshold) if l2i_threshold else None

row = None
with open(aggregate, newline="", encoding="utf-8") as f:
    for item in csv.DictReader(f):
        if item.get("variant") == variant:
            row = item
            break
if not row or row.get("status") != "ok":
    sys.exit(1)

def val(name):
    try:
        out = float(row.get(name, "nan"))
    except ValueError:
        out = float("nan")
    return out

runtime = val("elapsed_delta_pct")
l2i = val("l2i_mpki_delta_pct")
runtime_ok = runtime_threshold is None or (math.isfinite(runtime) and runtime <= runtime_threshold)
l2i_ok = l2i_threshold is None or (math.isfinite(l2i) and l2i <= l2i_threshold)
sys.exit(0 if runtime_ok and l2i_ok else 1)
PY
    then
      log "stop threshold reached by ${run_id}; stopping screening"
      return 1
    fi
  fi
  if [[ "${EARLY_STOP_WORSE_STREAK}" =~ ^[0-9]+$ && "${EARLY_STOP_WORSE_STREAK}" -gt 0 ]]; then
    if python3 - "${OUT_DIR}/aggregate.csv" "${EARLY_STOP_WORSE_STREAK}" "${EARLY_STOP_WORSE_MARGIN_PCT}" <<'PY'
import csv
import math
import re
import sys

aggregate, streak_s, margin_s = sys.argv[1:4]
streak = int(streak_s)
margin = float(margin_s) / 100.0

def num(row, key):
    try:
        return float(row.get(key, "nan"))
    except ValueError:
        return float("nan")

def idx(row):
    m = re.match(r"v([0-9]+)_", row.get("variant", ""))
    return int(m.group(1)) if m else 10**9

rows = []
with open(aggregate, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row.get("status") != "ok":
            continue
        elapsed = num(row, "elapsed_sec")
        injected = num(row, "pass_injected")
        if math.isfinite(elapsed) and math.isfinite(injected):
            rows.append(row)

if len(rows) < streak + 1:
    sys.exit(1)

rows.sort(key=idx)
best = min(rows, key=lambda r: num(r, "elapsed_sec"))
best_elapsed = num(best, "elapsed_sec")
best_injected = num(best, "pass_injected")
recent = rows[-streak:]
if not all(num(r, "pass_injected") >= best_injected for r in recent):
    sys.exit(1)
if all(num(r, "elapsed_sec") >= best_elapsed * (1.0 + margin) for r in recent):
    sys.exit(0)
sys.exit(1)
PY
    then
      log "early-stop: last ${EARLY_STOP_WORSE_STREAK} successful variants are worse than best runtime by >=${EARLY_STOP_WORSE_MARGIN_PCT}%"
      return 1
    fi
  fi
}

run_confirmation_if_possible() {
  local left
  left="$(seconds_left)"
  if (( left < 900 )); then
    log "skip confirmation: only ${left}s left"
    return 0
  fi
  if [[ ! -f "${OUT_DIR}/best_variant.txt" ]]; then
    log "skip confirmation: no successful variant"
    return 0
  fi

  local best_name best_dir best_bin
  mapfile -t best_lines < "${OUT_DIR}/best_variant.txt"
  best_name="${best_lines[0]:-}"
  best_dir="${best_lines[1]:-}"
  best_bin="${best_lines[2]:-}"
  if [[ -z "${best_bin}" || ! -f "${best_bin}" ]]; then
    log "skip confirmation: best binary missing"
    return 0
  fi

  log "confirmation profile for ${best_name}: iterations=${CONFIRM_ITERATIONS}"
  local confirm_base="${OUT_DIR}/confirmation_profile"
  "${PROFILING_DIR}/run_detailed_profile.sh" \
    --workload verilator-qsort \
    --workload-name "confirm_${best_name}" \
    --sim-binary "${best_bin}" \
    --max-cycles "${MAX_CYCLES}" \
    --iterations "${CONFIRM_ITERATIONS}" \
    --profile-core "${PROFILE_CORE}" \
    --perf-scope task \
    --results-base "${confirm_base}" > "${OUT_DIR}/confirmation_profile.log" 2>&1 || {
      log "confirmation profile failed; see ${OUT_DIR}/confirmation_profile.log"
      return 0
    }

  log "confirmation complete: ${confirm_base}/confirm_${best_name}/summary.csv"
}

require_file "${EVAL_SCRIPT}"
require_file "${SUMMARY_TOOL}"
require_file "${BASELINE_BINARY}"
require_file "${BASELINE_SUMMARY}"
require_trace_inputs
require_dir "${SOURCE_WORK}"

cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
start_epoch=${START_EPOCH}
deadline_epoch=${DEADLINE_EPOCH}
autotune_hours=${AUTOTUNE_HOURS}
baseline_binary=${BASELINE_BINARY}
baseline_summary=${BASELINE_SUMMARY}
trace_input=${TRACE_INPUT}
trace_inputs=${TRACE_INPUTS}
target_coverage_pct_default=${TARGET_COVERAGE_PCT}
max_cycles=${MAX_CYCLES}
screen_iterations=${SCREEN_ITERATIONS}
trace_duration_sec=${TRACE_DURATION_SEC}
trace_sample_period=${TRACE_SAMPLE_PERIOD}
build_jobs=${BUILD_JOBS}
prefetch_byte_offsets_default=${PREFETCH_BYTE_OFFSETS}
branch_depth_policy_default=${BRANCH_DEPTH_POLICY}
summary_rank_by=${SUMMARY_RANK_BY}
early_stop_worse_streak=${EARLY_STOP_WORSE_STREAK}
early_stop_worse_margin_pct=${EARLY_STOP_WORSE_MARGIN_PCT}
EOF

log "autotune start: out=${OUT_DIR}"
log "deadline: $(date -d "@${DEADLINE_EPOCH}" '+%F %T')"

index=0
run_variants_from_stream() {
  local raw_line name top_k depth_min depth budget mode sites_per_depth candidate_pool target_coverage_pct prefetch_byte_offsets branch_depth_policy
  local -a variant_lines
  local -a fields

  # Read the whole variant list up front. Each variant can take tens of minutes
  # to build, and keeping a file descriptor open across those long builds makes
  # the loop fragile if the variants file is regenerated in the meantime.
  variant_lines=()
  while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
    variant_lines+=("${raw_line}")
  done

  for raw_line in "${variant_lines[@]}"; do
    raw_line="${raw_line%$'\r'}"
    [[ -z "${raw_line//[[:space:]]/}" || "${raw_line}" =~ ^[[:space:]]*# ]] && continue

    IFS='|' read -r -a fields <<< "${raw_line}"
    if (( ${#fields[@]} < 10 )); then
      log "skip malformed variant line: expected at least 10 pipe fields, got ${#fields[@]}: ${raw_line}"
      continue
    fi
    name="${fields[0]}"
    top_k="${fields[1]}"
    depth_min="${fields[2]}"
    depth="${fields[3]}"
    budget="${fields[4]}"
    mode="${fields[5]}"
    sites_per_depth="${fields[6]}"
    candidate_pool="${fields[7]}"
    target_coverage_pct="${fields[8]:-${TARGET_COVERAGE_PCT}}"
    prefetch_byte_offsets="${fields[9]:-${PREFETCH_BYTE_OFFSETS}}"
    branch_depth_policy="${fields[10]:-${BRANCH_DEPTH_POLICY}}"

    if [[ -z "${name}" || "${name}" =~ ^[0-9]+$ || ! "${top_k}" =~ ^[0-9]+$ || ! "${depth_min}" =~ ^[0-9]+$ || ! "${depth}" =~ ^[0-9]+$ || ! "${target_coverage_pct}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
      log "skip malformed variant line: name/top_k/depth/coverage validation failed: ${raw_line}"
      continue
    fi

    index=$((index + 1))
    run_variant "${index}" "${name}" "${top_k}" "${depth_min}" "${depth}" "${budget}" "${mode}" "${sites_per_depth}" "${candidate_pool}" "${target_coverage_pct}" "${prefetch_byte_offsets}" "${branch_depth_policy}" || break
  done
}

if [[ -n "${VARIANTS_FILE}" ]]; then
  require_file "${VARIANTS_FILE}"
  log "using variants file: ${VARIANTS_FILE}"
  run_variants_from_stream < "${VARIANTS_FILE}"
else
  run_variants_from_stream <<'EOF'
cov50_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|50|0,64,128,192
cov75_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|75|0,64,128,192
cov50_allpaths_d1_32_o4|999999|1|32|0|all-paths|1|0|50|0,64,128,192
cov75_allpaths_d1_32_o4|999999|1|32|0|all-paths|1|0|75|0,64,128,192
cov50_allpaths_d4_16_o8|999999|4|16|0|all-paths|1|0|50|0,64,128,192,256,320,384,448
cov75_allpaths_d4_16_o8|999999|4|16|0|all-paths|1|0|75|0,64,128,192,256,320,384,448
cov100_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|100|0,64,128,192
cov100_allpaths_d1_32_o4|999999|1|32|0|all-paths|1|0|100|0,64,128,192
cov50_allpaths_d4_8_o1|999999|4|8|0|all-paths|1|0|50|0
cov50_allpaths_d4_8_o2|999999|4|8|0|all-paths|1|0|50|0,64
cov50_allpaths_d8_16_o2|999999|8|16|0|all-paths|1|0|50|0,64
cov50_allpaths_d16_32_o2|999999|16|32|0|all-paths|1|0|50|0,64
cov50_allpaths_d4_16_shift4|999999|4|16|0|all-paths|1|0|50|64,128,192,256
cov50_tops_d4_16_b1_o2|999999|4|16|1|top-sites|1|0|50|0,64
cov50_tops_d4_16_b2_o2|999999|4|16|2|top-sites|1|0|50|0,64
cov50_tops_d4_16_b4_o2|999999|4|16|4|top-sites|1|0|50|0,64
cov75_tops_d4_16_b2_o2|999999|4|16|2|top-sites|1|0|75|0,64
cov50_greedy_d4_16_b8_o2|999999|4|16|8|greedy|1|10000|50|0,64
cov75_greedy_d4_16_b8_o2|999999|4|16|8|greedy|1|10000|75|0,64
cov50_perdepth_d4_16_b16_o2|999999|4|16|16|per-depth|1|0|50|0,64
cov50_perdepth_d1_32_b32_o2|999999|1|32|32|per-depth|1|0|50|0,64
EOF
fi

if [[ "${RUN_CONFIRMATION}" == "1" ]]; then
  run_confirmation_if_possible
else
  log "skip confirmation: RUN_CONFIRMATION=${RUN_CONFIRMATION}"
fi
log "autotune done"
