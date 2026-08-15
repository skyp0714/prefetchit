#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"

DURATION_HOURS="${DURATION_HOURS:-8}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
SCREEN_ITERATIONS="${SCREEN_ITERATIONS:-1}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
BUILD_JOBS="${BUILD_JOBS:-32}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE:-1}"
RESIDUAL_TRACE_DURATION_SEC="${RESIDUAL_TRACE_DURATION_SEC:-20}"
RESIDUAL_TRACE_SAMPLE_PERIOD="${RESIDUAL_TRACE_SAMPLE_PERIOD:-100000}"

OLD_PLATEAU_DIR="${OLD_PLATEAU_DIR:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/plateau_fixed_20260604_013311}"
RUN_ID="${RUN_ID:-resume_aggressive_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/${RUN_ID}}"
LOG="${OUT_DIR}/resume_aggressive_8h.log"
HEARTBEAT="${OUT_DIR}/heartbeat.txt"
VARIANTS_FILE="${OUT_DIR}/batches/aggressive_variants.txt"

BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_aggressive/aggressive_20260601_122543/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
TRACE_INPUTS="${TRACE_INPUTS:-}"

START_EPOCH="$(date +%s)"
DEADLINE_EPOCH="$((START_EPOCH + DURATION_HOURS * 3600))"

mkdir -p "${OUT_DIR}/batches" "${OUT_DIR}/logs"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"
}

heartbeat() {
  {
    echo "time=$(date '+%F %T')"
    echo "run_id=${RUN_ID}"
    echo "out_dir=${OUT_DIR}"
    echo "seconds_left=$(seconds_left)"
    df -h "${REPO_ROOT}" | tail -1
  } > "${HEARTBEAT}"
}

seconds_left() {
  echo $((DEADLINE_EPOCH - $(date +%s)))
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

load_trace_inputs() {
  if [[ -n "${TRACE_INPUTS}" ]]; then
    return
  fi
  if [[ -f "${OLD_PLATEAU_DIR}/manifest.txt" ]]; then
    TRACE_INPUTS="$(awk -F= '$1=="trace_inputs" {print substr($0, index($0,$2)); exit}' "${OLD_PLATEAU_DIR}/manifest.txt")"
  fi
  if [[ -z "${TRACE_INPUTS}" ]]; then
    local tbase="${LLVM_PREFETCH_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces"
    TRACE_INPUTS="${tbase}/baseline_qsort_${MAX_CYCLES}_trace01/l2_miss:${tbase}/baseline_qsort_${MAX_CYCLES}_trace02/l2_miss:${tbase}/baseline_qsort_${MAX_CYCLES}_trace03/l2_miss"
  fi
}

validate_inputs() {
  require_dir "${OLD_PLATEAU_DIR}"
  require_file "${BASELINE_BINARY}"
  require_file "${BASELINE_SUMMARY}"
  require_file "${BASELINE_PER_ITER}"
  require_dir "${SOURCE_WORK}"
  require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetch_scheme_compare_from_best.sh"
  require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh"
  require_file "${LLVM_PREFETCH_DIR}/tools/audit_final_prefetch_compare.py"
  load_trace_inputs

  local trace_dir found=0
  IFS=':' read -r -a trace_dirs <<< "${TRACE_INPUTS}"
  for trace_dir in "${trace_dirs[@]}"; do
    [[ -n "${trace_dir}" ]] || continue
    found=1
    require_file "${trace_dir}/lbr_symbolic_dump.txt"
  done
  if [[ "${found}" -eq 0 ]]; then
    echo "[err] TRACE_INPUTS is empty" | tee -a "${LOG}" >&2
    exit 1
  fi
}

disk_snapshot() {
  log "disk snapshot:"
  df -h "${REPO_ROOT}" | tee -a "${LOG}"
  du -sh "${LLVM_PREFETCH_DIR}/results" 2>/dev/null | tee -a "${LOG}" || true
}

cleanup_stale_copied_workdirs() {
  log "cleanup stale copied Verilator workdirs"
  find "${LLVM_PREFETCH_DIR}/results" \
    \( -path '*/prefetchit_same_positions*/same_*_prefetchit1/work' \
       -o -path '*/prefetchit_same_positions_resume*/same_*_prefetchit1/work' \
       -o -path '*/exact_best_compare/prefetchit_same_positions/same_*_prefetchit1/work' \) \
    -type d -prune -print -exec rm -rf {} + 2>/dev/null | tee -a "${LOG}" || true
  find "${OUT_DIR}" -path '*/work' -type d -prune -print -exec rm -rf {} + 2>/dev/null | tee -a "${LOG}" || true
}

copy_seed_aggregates() {
  local seed_dir="${OUT_DIR}/batch_seed"
  local dst="${seed_dir}/aggregate.csv"
  mkdir -p "${seed_dir}"
  python3 - "${OLD_PLATEAU_DIR}" "${dst}" <<'PY'
import csv
import sys
from pathlib import Path

old = Path(sys.argv[1])
dst = Path(sys.argv[2])
sources = sorted(old.glob("batch*/aggregate.csv"))
if not sources:
    raise SystemExit(f"no seed aggregates under {old}")

rows = []
fieldnames = None
seen = set()
for src in sources:
    with src.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if fieldnames is None:
            fieldnames = reader.fieldnames
        for row in reader:
            key = (row.get("variant", ""), row.get("run_dir", ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)

dst.parent.mkdir(parents=True, exist_ok=True)
with dst.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
print(f"[ok] copied {len(rows)} seed rows to {dst}")
PY
}

write_manifest() {
  cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
old_plateau_dir=${OLD_PLATEAU_DIR}
trace_inputs=${TRACE_INPUTS}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
screen_iterations=${SCREEN_ITERATIONS}
final_iterations=${FINAL_ITERATIONS}
build_jobs=${BUILD_JOBS}
duration_hours=${DURATION_HOURS}
deadline_epoch=${DEADLINE_EPOCH}
baseline_binary=${BASELINE_BINARY}
baseline_summary=${BASELINE_SUMMARY}
baseline_per_iter=${BASELINE_PER_ITER}
source_work=${SOURCE_WORK}
run_residual_trace=${RUN_RESIDUAL_TRACE}
EOF
}

write_aggressive_variants() {
  cat > "${VARIANTS_FILE}" <<'EOFVAR'
# Continue from the previous best by increasing target coverage, site coverage,
# and depth. The expensive all-path variants are intentionally later so earlier
# high-coverage top-site/per-depth variants can finish first if time is tight.
cov75_tops_d4_24_b16_o2|999999|4|24|16|top-sites|1|0|75|0,64|
cov100_tops_d4_24_b16_o2|999999|4|24|16|top-sites|1|0|100|0,64|
cov75_perdepth_d1_32_b96_o2|999999|1|32|96|per-depth|3|0|75|0,64|
cov100_perdepth_d1_32_b96_o2|999999|1|32|96|per-depth|3|0|100|0,64|
cov75_bp_tops_d1_32_b16_o2|999999|1|32|16|top-sites|1|0|75|0,64|CALL:1-8,IND_CALL:1-8,COND:2-24,UNCOND:2-24,RET:8-32,IND:4-32
cov100_bp_tops_d1_32_b16_o2|999999|1|32|16|top-sites|1|0|100|0,64|CALL:1-8,IND_CALL:1-8,COND:2-24,UNCOND:2-24,RET:8-32,IND:4-32
cov50_allpaths_d4_24_o2|999999|4|24|0|all-paths|1|0|50|0,64|
cov75_allpaths_d4_24_o2|999999|4|24|0|all-paths|1|0|75|0,64|
cov100_allpaths_d4_16_o2|999999|4|16|0|all-paths|1|0|100|0,64|
cov75_tops_d4_24_b16_o4|999999|4|24|16|top-sites|1|0|75|0,64,128,192|
cov100_tops_d4_24_b16_o4|999999|4|24|16|top-sites|1|0|100|0,64,128,192|
cov75_bp_tops_d1_32_b16_o4|999999|1|32|16|top-sites|1|0|75|0,64,128,192|CALL:1-8,IND_CALL:1-8,COND:2-24,UNCOND:2-24,RET:8-32,IND:4-32
cov100_bp_tops_d1_32_b16_o4|999999|1|32|16|top-sites|1|0|100|0,64,128,192|CALL:1-8,IND_CALL:1-8,COND:2-24,UNCOND:2-24,RET:8-32,IND:4-32
cov75_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|75|0,64,128,192|
cov100_allpaths_d4_16_o4|999999|4|16|0|all-paths|1|0|100|0,64,128,192|
EOFVAR
}

run_old_exact_compare() {
  local exact_dir="${OLD_PLATEAU_DIR}/exact_best_compare"
  if [[ -f "${exact_dir}/compare.done" ]]; then
    log "old exact compare already complete: ${exact_dir}"
    return 0
  fi

  local attempt rc jobs
  for attempt in 1 2; do
    jobs="${BUILD_JOBS}"
    if [[ "${attempt}" -eq 2 ]]; then
      jobs=16
    fi
    cleanup_stale_copied_workdirs
    log "old exact compare attempt ${attempt}: jobs=${jobs}"
    set +e
    PLATEAU_DIR="${OLD_PLATEAU_DIR}" \
    OUT_DIR="${OLD_PLATEAU_DIR}/exact_best_compare" \
    TRACE_INPUTS="${TRACE_INPUTS}" \
    FINAL_ITERATIONS="${FINAL_ITERATIONS}" \
    PROFILE_CORE="${PROFILE_CORE}" \
    BUILD_JOBS="${jobs}" \
    RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE}" \
    RESIDUAL_TRACE_DURATION_SEC="${RESIDUAL_TRACE_DURATION_SEC}" \
    RESIDUAL_TRACE_SAMPLE_PERIOD="${RESIDUAL_TRACE_SAMPLE_PERIOD}" \
    MAX_CYCLES="${MAX_CYCLES}" \
    bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetch_scheme_compare_from_best.sh" \
      > "${OLD_PLATEAU_DIR}/exact_best_compare.driver.log" 2>&1
    rc=$?
    set -e
    if [[ "${rc}" -eq 0 && -f "${exact_dir}/compare.done" ]]; then
      touch "${OLD_PLATEAU_DIR}/finalize.done"
      log "old exact compare complete"
      audit_exact_compare "${exact_dir}" "${OLD_PLATEAU_DIR}/final_prefetch_compare_audit.md" || true
      return 0
    fi
    log "old exact compare failed rc=${rc}; tail follows"
    tail -80 "${OLD_PLATEAU_DIR}/exact_best_compare.driver.log" | tee -a "${LOG}" || true
    if (( $(seconds_left) < 5400 )); then
      log "not enough time for another old exact compare retry"
      break
    fi
  done
  return 1
}

run_aggressive_batch() {
  local left hours rc
  left="$(seconds_left)"
  if (( left < 7200 )); then
    log "skip aggressive batch: only ${left}s left; reserve time for final compare"
    return 0
  fi
  hours=$(( (left - 7200) / 3600 ))
  if (( hours < 1 )); then
    hours=1
  fi
  log "aggressive prefetcht1 batch start: autotune_hours=${hours}"
  set +e
  RUN_ID="batch_aggressive" \
  OUT_DIR="${OUT_DIR}/batch_aggressive" \
  VARIANTS_FILE="${VARIANTS_FILE}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  TRACE_INPUT="${TRACE_INPUTS%%:*}" \
  BASELINE_BINARY="${BASELINE_BINARY}" \
  BASELINE_SUMMARY="${BASELINE_SUMMARY}" \
  SOURCE_WORK="${SOURCE_WORK}" \
  AUTOTUNE_HOURS="${hours}" \
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
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_autotune.sh" \
    > "${OUT_DIR}/batch_aggressive.driver.log" 2>&1
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 ]]; then
    log "aggressive batch exited rc=${rc}; continuing if aggregate exists"
    tail -80 "${OUT_DIR}/batch_aggressive.driver.log" | tee -a "${LOG}" || true
  fi
  cleanup_stale_copied_workdirs
}

best_runtime_delta() {
  local dir="$1"
  python3 - "${dir}" <<'PY'
import csv
import math
import sys
from pathlib import Path

root = Path(sys.argv[1])
best = None
for aggregate in sorted(root.glob("batch*/aggregate.csv")):
    with aggregate.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "ok":
                continue
            try:
                delta = float(row.get("elapsed_delta_pct", "nan"))
            except ValueError:
                continue
            if not math.isfinite(delta):
                continue
            binary = Path(row.get("binary", ""))
            plan = Path(row.get("run_dir", "")) / "plan" / "prefetcht1.plan.json"
            if not binary.is_file() or not plan.is_file():
                continue
            item = (delta, row.get("variant", ""), row.get("run_dir", ""), str(binary))
            if best is None or item[0] < best[0]:
                best = item
if best is None:
    print("nan\t\t\t")
else:
    print("\t".join(str(x) for x in best))
PY
}

audit_exact_compare() {
  local exact_dir="$1"
  local out="$2"
  python3 "${LLVM_PREFETCH_DIR}/tools/audit_final_prefetch_compare.py" \
    --exact-dir "${exact_dir}" \
    --out "${out}"
}

run_resume_exact_compare_if_needed() {
  local old_line new_line old_delta new_delta new_name rc
  old_line="$(best_runtime_delta "${OLD_PLATEAU_DIR}" || true)"
  new_line="$(best_runtime_delta "${OUT_DIR}" || true)"
  IFS=$'\t' read -r old_delta _ <<< "${old_line}"
  IFS=$'\t' read -r new_delta new_name _ <<< "${new_line}"

  log "best old runtime delta: ${old_delta}"
  log "best resume runtime delta: ${new_delta} variant=${new_name:-none}"

  if [[ -f "${OUT_DIR}/exact_best_compare/compare.done" ]]; then
    log "resume exact compare already complete"
    return 0
  fi

  if python3 - "${old_delta}" "${new_delta}" <<'PY'
import math
import sys
old = float(sys.argv[1])
new = float(sys.argv[2])
sys.exit(0 if math.isfinite(new) and (not math.isfinite(old) or new < old - 0.1) else 1)
PY
  then
    log "new aggressive best improves over old; run same-position prefetchit1 compare on resume root"
  else
    if [[ -f "${OLD_PLATEAU_DIR}/exact_best_compare/compare.done" ]]; then
      log "new aggressive best did not improve enough; old exact compare is final"
      return 0
    fi
    log "old exact compare is unavailable; run resume exact compare anyway"
  fi

  set +e
  PLATEAU_DIR="${OUT_DIR}" \
  OUT_DIR="${OUT_DIR}/exact_best_compare" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  FINAL_ITERATIONS="${FINAL_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE}" \
  RESIDUAL_TRACE_DURATION_SEC="${RESIDUAL_TRACE_DURATION_SEC}" \
  RESIDUAL_TRACE_SAMPLE_PERIOD="${RESIDUAL_TRACE_SAMPLE_PERIOD}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetch_scheme_compare_from_best.sh" \
    > "${OUT_DIR}/exact_best_compare.driver.log" 2>&1
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 ]]; then
    log "resume exact compare failed rc=${rc}; tail follows"
    tail -100 "${OUT_DIR}/exact_best_compare.driver.log" | tee -a "${LOG}" || true
    return "${rc}"
  fi
  audit_exact_compare "${OUT_DIR}/exact_best_compare" "${OUT_DIR}/final_prefetch_compare_audit.md" || true
}

write_final_status() {
  local old_line new_line final_exact
  old_line="$(best_runtime_delta "${OLD_PLATEAU_DIR}" || true)"
  new_line="$(best_runtime_delta "${OUT_DIR}" || true)"
  final_exact="${OUT_DIR}/exact_best_compare"
  if [[ ! -f "${final_exact}/compare.done" && -f "${OLD_PLATEAU_DIR}/exact_best_compare/compare.done" ]]; then
    final_exact="${OLD_PLATEAU_DIR}/exact_best_compare"
  fi

  {
    echo "# Resume Aggressive Prefetch 8h Status"
    echo
    echo "- Run id: \`${RUN_ID}\`"
    echo "- Out dir: \`${OUT_DIR}\`"
    echo "- Old plateau dir: \`${OLD_PLATEAU_DIR}\`"
    echo "- Old best runtime delta/name/run/bin: \`${old_line}\`"
    echo "- Resume best runtime delta/name/run/bin: \`${new_line}\`"
    echo "- Final exact compare dir: \`${final_exact}\`"
    echo "- Old exact compare done: $([[ -f "${OLD_PLATEAU_DIR}/exact_best_compare/compare.done" ]] && echo yes || echo no)"
    echo "- Resume exact compare done: $([[ -f "${OUT_DIR}/exact_best_compare/compare.done" ]] && echo yes || echo no)"
    echo
    if [[ -f "${final_exact}/final_compare/prefetch_compare_summary.md" ]]; then
      cat "${final_exact}/final_compare/prefetch_compare_summary.md"
    fi
  } > "${OUT_DIR}/resume_aggressive_final_status.md"
  log "final status: ${OUT_DIR}/resume_aggressive_final_status.md"
}

main() {
  validate_inputs
  write_manifest
  write_aggressive_variants
  log "resume aggressive 8h start: out=${OUT_DIR} deadline=$(date -d "@${DEADLINE_EPOCH}" '+%F %T')"
  disk_snapshot
  heartbeat
  cleanup_stale_copied_workdirs
  copy_seed_aggregates | tee -a "${LOG}"

  run_old_exact_compare || log "old exact compare did not complete; continue aggressive search"
  heartbeat
  disk_snapshot

  run_aggressive_batch
  heartbeat
  disk_snapshot

  run_resume_exact_compare_if_needed || log "resume exact compare did not complete"
  heartbeat
  write_final_status
  disk_snapshot
  log "resume aggressive 8h done"
}

main "$@"
