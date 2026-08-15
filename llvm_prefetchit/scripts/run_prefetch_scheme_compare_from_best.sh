#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"
BENCH_COMMON="${PROFILING_DIR}/runscript/bench/bench_common.sh"

CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
FINAL_ITERATIONS="${FINAL_ITERATIONS:-5}"
BUILD_JOBS="${BUILD_JOBS:-$(nproc)}"
RUN_RESIDUAL_TRACE="${RUN_RESIDUAL_TRACE:-1}"
RESIDUAL_TRACE_DURATION_SEC="${RESIDUAL_TRACE_DURATION_SEC:-20}"
RESIDUAL_TRACE_SAMPLE_PERIOD="${RESIDUAL_TRACE_SAMPLE_PERIOD:-100000}"

PLATEAU_DIR="${PLATEAU_DIR:-}"
if [[ -z "${PLATEAU_DIR}" ]]; then
  PLATEAU_DIR="$(find "${LLVM_PREFETCH_DIR}/results/prefetch_plateau" -maxdepth 1 -type d -name 'plateau*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)"
fi
if [[ -z "${PLATEAU_DIR}" || ! -d "${PLATEAU_DIR}" ]]; then
  echo "[err] PLATEAU_DIR is required or no plateau results were found" >&2
  exit 1
fi

OUT_DIR="${OUT_DIR:-${PLATEAU_DIR}/exact_best_compare}"
COMPARE_DIR="${OUT_DIR}/final_compare"
LOG="${OUT_DIR}/compare.log"
mkdir -p "${OUT_DIR}" "${COMPARE_DIR}/profiles"

BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetcht1_l2_eval/20260531_234218/detailed_profile/baseline_qsort_${MAX_CYCLES}/summary.csv}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_aggressive/aggressive_20260601_122543/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
TRACE_INPUTS="${TRACE_INPUTS:-}"
if [[ -z "${TRACE_INPUTS}" && -f "${PLATEAU_DIR}/manifest.txt" ]]; then
  TRACE_INPUTS="$(awk -F= '$1=="trace_inputs" {print substr($0, index($0,$2)); exit}' "${PLATEAU_DIR}/manifest.txt")"
fi

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

require_file "${BASELINE_BINARY}"
require_file "${BASELINE_SUMMARY}"
require_file "${BASELINE_PER_ITER}"
require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh"
require_file "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_compare.py"
require_file "${BENCH_COMMON}"

pick_best_run() {
  python3 - "${PLATEAU_DIR}" <<'PY'
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
            run_dir = Path(row.get("run_dir", ""))
            binary = Path(row.get("binary", ""))
            plan = run_dir / "plan" / "prefetcht1.plan.json"
            if not run_dir.is_dir() or not binary.is_file() or not plan.is_file():
                continue
            item = (delta, row.get("variant", ""), str(run_dir), str(binary))
            if best is None or item[0] < best[0]:
                best = item
if best is None:
    raise SystemExit(1)
print("\t".join(str(x) for x in best))
PY
}

extract_plan_options() {
  local plan="$1"
  python3 - "$plan" <<'PY'
import json
import shlex
import sys

p = json.load(open(sys.argv[1], encoding="utf-8"))
o = p.get("options", {})
policy = o.get("branch_depth_policy") or {}
policy_s = ",".join(
    f"{k}:{v[0]}-{v[1]}" for k, v in sorted(policy.items())
    if isinstance(v, list) and len(v) == 2
)
items = {
    "TOP_K": o.get("top_k", 999999),
    "TARGET_COVERAGE_PCT": o.get("target_coverage_pct", 0),
    "DEPTH_MIN": o.get("depth_min", 4),
    "DEPTH": o.get("depth", 16),
    "SITE_BUDGET": o.get("site_budget_per_target", 1),
    "SELECTION_MODE": o.get("selection_mode", "top-sites"),
    "SITES_PER_DEPTH": o.get("sites_per_depth", 1),
    "CANDIDATE_POOL": o.get("candidate_pool", 0),
    "PREFETCH_BYTE_OFFSETS": ",".join(str(x) for x in o.get("prefetch_byte_offsets", [0])),
    "BRANCH_DEPTH_POLICY": policy_s,
}
for k, v in items.items():
    print(f"{k}={shlex.quote(str(v))}")
PY
}

run_profile() {
  local label="$1"
  local bin="$2"
  log "profile ${label}: iterations=${FINAL_ITERATIONS} core=${PROFILE_CORE}"
  "${PROFILING_DIR}/run_detailed_profile.sh" \
    --workload verilator-qsort \
    --workload-name "${label}_qsort_${MAX_CYCLES}" \
    --sim-binary "${bin}" \
    --max-cycles "${MAX_CYCLES}" \
    --iterations "${FINAL_ITERATIONS}" \
    --profile-core "${PROFILE_CORE}" \
    --perf-scope task \
    --results-base "${COMPARE_DIR}/profiles" \
    > "${COMPARE_DIR}/${label}_profile.log" 2>&1
}

run_residual_trace() {
  local label="$1"
  local bin="$2"
  local trace_base="${OUT_DIR}/residual_trace"
  mkdir -p "${trace_base}"
  log "residual L2 trace ${label}: duration=${RESIDUAL_TRACE_DURATION_SEC}s period=${RESIDUAL_TRACE_SAMPLE_PERIOD}"
  "${PROFILING_DIR}/run_pebs_sampling.sh" \
    --workload verilator-qsort \
    --workload-name "${label}_qsort_${MAX_CYCLES}" \
    --sim-binary "${bin}" \
    --max-cycles "${MAX_CYCLES}" \
    --profile-core "${PROFILE_CORE}" \
    --perf-scope task \
    --duration-sec "${RESIDUAL_TRACE_DURATION_SEC}" \
    --sample-period "${RESIDUAL_TRACE_SAMPLE_PERIOD}" \
    --trace-mode split \
    --trace-select l2 \
    --run-analyze 1 \
    --results-base "${trace_base}" \
    --use-ocperf 0 \
    --event-l2 'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp' \
    > "${trace_base}/${label}_trace.log" 2>&1 || {
      log "residual trace failed for ${label}; see ${trace_base}/${label}_trace.log"
      return 0
    }
}

rewrite_plan_mnemonic() {
  local src_plan="$1"
  local dst_plan="$2"
  local mnemonic="$3"
  mkdir -p "$(dirname "${dst_plan}")"
  python3 - "${src_plan}" "${dst_plan}" "${mnemonic}" <<'PY'
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
mnemonic = sys.argv[3]
plan = json.load(src.open(encoding="utf-8"))
plan["prefetch_mnemonic"] = mnemonic
plan.setdefault("prefetch", {})["mnemonic"] = mnemonic
plan.setdefault("options", {})["prefetch_mnemonic"] = mnemonic
for inj in plan.get("injections", []):
    inj["prefetch_mnemonic"] = mnemonic
    if isinstance(inj.get("prefetch"), dict):
        inj["prefetch"]["mnemonic"] = mnemonic
dst.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"[ok] wrote {dst}")
PY
}

rewrite_verilator_makefile() {
  local mk="$1"
  local work_dir="$2"
  local sim_out="$3"
  python3 - <<'PY' "${mk}" "${SOURCE_WORK}" "${work_dir}" "${CONFIG}" "${sim_out}"
from pathlib import Path
import re
import sys

mk = Path(sys.argv[1])
source_work = sys.argv[2]
work_dir = sys.argv[3]
config = sys.argv[4]
sim_out = sys.argv[5]
text = mk.read_text()
before = text
text = text.replace(source_work, work_dir)
target_re = re.compile(
    r"\S*simulator-chipyard\.harness-" + re.escape(config) + r"(?:-llvm-[^\s:]+)?"
)
text, target_rewrites = target_re.subn(sim_out, text)
mk.write_text(text)
print(
    f"[inf] VTestDriver.mk rewrites: path_changed={before != text} "
    f"simulator_target_rewrites={target_rewrites}"
)
if sim_out not in text:
    raise SystemExit("SIM_OUT target not found after VTestDriver.mk rewrite")
PY
}

build_prefetchit_from_exact_plan() {
  local src_plan="$1"
  local run_dir="$2"
  local final_bin="$3"
  local plan="${run_dir}/plan/prefetchit1.plan.json"
  local asm_dir="${run_dir}/assembly_validation"
  local work_dir="${run_dir}/work/verilator_prefetchit1"
  local model_dir="${work_dir}/generated-src/chipyard.harness.TestHarness.${CONFIG}/chipyard.harness.TestHarness.${CONFIG}"
  local sim_out="${work_dir}/simulator-chipyard.harness-${CONFIG}-llvm-prefetchit1"
  local build_log="${run_dir}/build/build_prefetchit1.log"
  local plugin="${LLVM_PREFETCH_DIR}/build/PrefetchITPass.so"

  source "${BENCH_COMMON}"
  setup_verilator_env
  require_chipyard_tree
  mkdir -p "${run_dir}/build" "${run_dir}/bin" "${asm_dir}"

  log "build LLVM pass for exact-plan prefetchit1"
  cmake --build "${LLVM_PREFETCH_DIR}/build"
  "${LLVM_PREFETCH_DIR}/tests/smoke/run_smoke.sh" "${LLVM_PREFETCH_DIR}/build"
  require_file "${plugin}"

  log "rewrite exact prefetcht1 plan to prefetchit1"
  rewrite_plan_mnemonic "${src_plan}" "${plan}" "prefetchit1"

  log "copy Verilator workdir for exact-plan prefetchit1"
  rm -rf "${work_dir}"
  mkdir -p "$(dirname "${work_dir}")"
  cp -a "${SOURCE_WORK}" "${work_dir}"
  require_file "${model_dir}/VTestDriver.mk"
  {
    echo "[run] $(date)"
    echo "[inf] PLAN=${plan}"
    echo "[inf] MODEL_DIR=${model_dir}"
    echo "[inf] SIM_OUT=${sim_out}"
    echo "[inf] FINAL_BIN=${final_bin}"
  } > "${build_log}"
  rewrite_verilator_makefile "${model_dir}/VTestDriver.mk" "${work_dir}" "${sim_out}" | tee -a "${build_log}"

  rm -f \
    "${model_dir}/VTestDriver__ALL.o" \
    "${model_dir}/VTestDriver__ALL.a" \
    "${model_dir}/VTestDriver__ALL.d" \
    "${model_dir}/VTestDriver__ALL.verilator_deplist.tmp" \
    "${sim_out}"

  (
    cd "${model_dir}"
    PREFETCHIT_PLAN="${plan}" \
    make -f VTestDriver.mk "${sim_out}" \
      -j"${BUILD_JOBS}" \
      VM_PARALLEL_BUILDS=0 \
      CXX="${CLANG_CXX:-clang++-19}" \
      LINK="${CLANG_CXX:-clang++-19}" \
      OPT_FAST="-O3 -fpass-plugin=${plugin}" \
      2>&1 | tee -a "${build_log}"
  )
  require_file "${sim_out}"
  cp -f "${sim_out}" "${final_bin}"
  require_file "${final_bin}"

  log "validate exact-plan prefetchit1 assembly"
  python3 "${LLVM_PREFETCH_DIR}/tools/validate_prefetch_asm.py" \
    --binary "${final_bin}" \
    --plan "${plan}" \
    --build-log "${build_log}" \
    --out-dir "${asm_dir}" \
    --mnemonic prefetchit1 \
    --objdump llvm-objdump-19 \
    --addr2line llvm-addr2line-19

  log "quick prefetchit1 smoke"
  local qbin="${RISCV_ROOT}/riscv64-unknown-elf/share/riscv-tests/benchmarks/qsort.riscv"
  require_file "${qbin}"
  set +e
  taskset -c "${PROFILE_CORE}" "${final_bin}" "${qbin}" +max-cycles=80000 > "${run_dir}/build/smoke_qsort.log" 2>&1
  local smoke_rc=$?
  set -e
  if [[ "${smoke_rc}" -ne 0 ]] && ! grep -q "(timeout)" "${run_dir}/build/smoke_qsort.log"; then
    echo "[err] prefetchit1 smoke failed rc=${smoke_rc}" >&2
    sed -n '1,120p' "${run_dir}/build/smoke_qsort.log" >&2
    exit 1
  fi
  rm -rf "${work_dir}"
}

validate_compare_outputs() {
  python3 - "${COMPARE_DIR}" <<'PY'
import csv
import math
import sys
from pathlib import Path

root = Path(sys.argv[1])
summary = root / "prefetch_compare_summary.csv"
if not summary.is_file():
    raise SystemExit(f"missing {summary}")
with summary.open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
if len(rows) < 3:
    raise SystemExit("comparison summary must include baseline, prefetcht1, and prefetchit1")
for row in rows:
    for key in ("elapsed_sec_mean", "l2i_mpki_mean"):
        value = float(row.get(key, "nan"))
        if not math.isfinite(value) or value <= 0.0:
            raise SystemExit(f"invalid {key}={value!r} for {row.get('label')}")
print("[ok] final compare numeric validation passed")
PY
}

main() {
  log "compare start: plateau=${PLATEAU_DIR}"
  local best_line
  best_line="$(pick_best_run)"
  IFS=$'\t' read -r BEST_DELTA BEST_NAME BEST_DIR BEST_BIN <<< "${best_line}"
  require_file "${BEST_BIN}"
  require_file "${BEST_DIR}/plan/prefetcht1.plan.json"
  log "best exact prefetcht1: ${BEST_NAME} delta=${BEST_DELTA}% bin=${BEST_BIN}"

  mkdir -p "${COMPARE_DIR}/profiles/baseline_qsort_${MAX_CYCLES}"
  cp -f "${BASELINE_PER_ITER}" "${COMPARE_DIR}/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv"
  cp -f "${BASELINE_SUMMARY}" "${COMPARE_DIR}/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv"

  eval "$(extract_plan_options "${BEST_DIR}/plan/prefetcht1.plan.json")"
  local prefetchit_base="${OUT_DIR}/prefetchit_same_positions"
  local prefetchit_run_id="same_${BEST_NAME}_prefetchit1"
  local prefetchit_dir="${prefetchit_base}/${prefetchit_run_id}"
  local prefetchit_bin="${prefetchit_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-prefetchit1"

  if [[ ! -x "${prefetchit_bin}" ]]; then
    log "build prefetchit1 at the exact same sites/targets as best prefetcht1"
    build_prefetchit_from_exact_plan \
      "${BEST_DIR}/plan/prefetcht1.plan.json" \
      "${prefetchit_dir}" \
      "${prefetchit_bin}" \
      > "${OUT_DIR}/prefetchit1_build_eval.log" 2>&1
  fi
  require_file "${prefetchit_bin}"

  run_profile prefetcht1 "${BEST_BIN}"
  run_profile prefetchit1 "${prefetchit_bin}"

  python3 "${LLVM_PREFETCH_DIR}/tools/plot_prefetch_compare.py" \
    --input "baseline=${COMPARE_DIR}/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv" \
    --input "prefetcht1=${COMPARE_DIR}/profiles/prefetcht1_qsort_${MAX_CYCLES}/per_iteration.csv" \
    --input "prefetchit1=${COMPARE_DIR}/profiles/prefetchit1_qsort_${MAX_CYCLES}/per_iteration.csv" \
    --out-dir "${COMPARE_DIR}"
  validate_compare_outputs | tee -a "${LOG}"

  if [[ "${RUN_RESIDUAL_TRACE}" == "1" ]]; then
    run_residual_trace prefetcht1 "${BEST_BIN}"
    run_residual_trace prefetchit1 "${prefetchit_bin}"
  fi

  {
    echo "# Exact-Target Prefetch Scheme Compare"
    echo
    echo "- Plateau dir: \`${PLATEAU_DIR}\`"
    echo "- Best exact prefetcht1 variant: \`${BEST_NAME}\`"
    echo "- Best exact prefetcht1 runtime delta: ${BEST_DELTA}%"
    echo "- Prefetcht1 binary: \`${BEST_BIN}\`"
    echo "- Prefetchit1 binary: \`${prefetchit_bin}\`"
    echo "- Iterations: ${FINAL_ITERATIONS}"
    echo "- Core: ${PROFILE_CORE}"
    echo
    cat "${COMPARE_DIR}/prefetch_compare_summary.md"
    echo
    echo "## Artifacts"
    echo
    echo "- Comparison CSV: \`${COMPARE_DIR}/prefetch_compare_summary.csv\`"
    echo "- Iteration CSV: \`${COMPARE_DIR}/prefetch_compare_iterations.csv\`"
    echo "- Boxplot: \`${COMPARE_DIR}/prefetch_compare_boxplot.png\`"
    echo "- Prefetchit validation: \`${prefetchit_dir}/assembly_validation/prefetch_asm_validation.md\`"
    echo "- Residual trace: \`${OUT_DIR}/residual_trace\`"
  } > "${OUT_DIR}/exact_prefetch_compare_report.md"
  touch "${OUT_DIR}/compare.done"
  log "compare complete: ${OUT_DIR}/exact_prefetch_compare_report.md"
}

main "$@"
