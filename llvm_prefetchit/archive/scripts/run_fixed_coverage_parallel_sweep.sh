#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-fixedcov50_parallel_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/prefetch_fixedcov_sweep/${RUN_ID}}"
RUNS_DIR="${OUT_DIR}/runs"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-3}"
PARALLEL_BUILDS="${PARALLEL_BUILDS:-6}"
BUILD_JOBS="${BUILD_JOBS:-16}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
COVERAGE_PCT="${COVERAGE_PCT:-50}"
BASELINE_BINARY="${BASELINE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv}"
SOURCE_WORK="${SOURCE_WORK:-${LLVM_PREFETCH_DIR}/work/verilator_llvm_prefetchit}"
BEST_PLAN="${BEST_PLAN:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/plateau_fixed_20260604_013311/batch_repair/runs/v02_cov50_tops_d4_24_b8_o2/plan/prefetcht1.plan.json}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
PREFETCH_LABEL="${PREFETCH_LABEL:-prefetcht1}"
SUMMARY_RANK_BY="${SUMMARY_RANK_BY:-l2i}"
VARIANTS_TSV_INPUT="${VARIANTS_TSV_INPUT:-}"
EARLY_STOP_WORSE_STREAK="${EARLY_STOP_WORSE_STREAK:-0}"
EARLY_STOP_WORSE_MARGIN_PCT="${EARLY_STOP_WORSE_MARGIN_PCT:-1.0}"
PROFILE_VARIANT_LIMIT="${PROFILE_VARIANT_LIMIT:-0}"
VARIANTS_TSV="${OUT_DIR}/fixedcov_variants.tsv"
METADATA_CSV="${OUT_DIR}/variant_metadata.csv"
BUILD_STATUS_TSV="${OUT_DIR}/build_status.tsv"
PROFILE_STATUS_TSV="${OUT_DIR}/profile_status.tsv"
LOG="${OUT_DIR}/fixedcov_parallel_sweep.log"

mkdir -p "${OUT_DIR}" "${RUNS_DIR}"

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

append_status() {
  local file="$1"
  shift
  {
    flock 9
    local IFS=$'\t'
    printf '%s\n' "$*"
  } 9>"${file}.lock" >> "${file}"
}

write_variants() {
  if [[ -n "${VARIANTS_TSV_INPUT}" ]]; then
    require_file "${VARIANTS_TSV_INPUT}"
    cp "${VARIANTS_TSV_INPUT}" "${VARIANTS_TSV}"
  else
    cat > "${VARIANTS_TSV}" <<EOF
# axis	value	name	top_k	depth_min	depth	site_budget	selection_mode	sites_per_depth	candidate_pool	target_coverage_pct	prefetch_byte_offsets	branch_depth_policy
baseline	best	cov${COVERAGE_PCT}_tops_d4_24_b8_o2	999999	4	24	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
budget	4	cov${COVERAGE_PCT}_tops_d4_24_b4_o2	999999	4	24	4	top-sites	1	0	${COVERAGE_PCT}	0,64	
budget	6	cov${COVERAGE_PCT}_tops_d4_24_b6_o2	999999	4	24	6	top-sites	1	0	${COVERAGE_PCT}	0,64	
budget	10	cov${COVERAGE_PCT}_tops_d4_24_b10_o2	999999	4	24	10	top-sites	1	0	${COVERAGE_PCT}	0,64	
budget	12	cov${COVERAGE_PCT}_tops_d4_24_b12_o2	999999	4	24	12	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_max	16	cov${COVERAGE_PCT}_tops_d4_16_b8_o2	999999	4	16	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_max	20	cov${COVERAGE_PCT}_tops_d4_20_b8_o2	999999	4	20	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_max	22	cov${COVERAGE_PCT}_tops_d4_22_b8_o2	999999	4	22	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_max	26	cov${COVERAGE_PCT}_tops_d4_26_b8_o2	999999	4	26	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_max	28	cov${COVERAGE_PCT}_tops_d4_28_b8_o2	999999	4	28	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_min	2	cov${COVERAGE_PCT}_tops_d2_24_b8_o2	999999	2	24	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_min	3	cov${COVERAGE_PCT}_tops_d3_24_b8_o2	999999	3	24	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_min	5	cov${COVERAGE_PCT}_tops_d5_24_b8_o2	999999	5	24	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
depth_min	6	cov${COVERAGE_PCT}_tops_d6_24_b8_o2	999999	6	24	8	top-sites	1	0	${COVERAGE_PCT}	0,64	
offsets	0	cov${COVERAGE_PCT}_tops_d4_24_b8_o1	999999	4	24	8	top-sites	1	0	${COVERAGE_PCT}	0	
offsets	0_64_128	cov${COVERAGE_PCT}_tops_d4_24_b8_o3	999999	4	24	8	top-sites	1	0	${COVERAGE_PCT}	0,64,128	
selection	branch_policy	cov${COVERAGE_PCT}_bp_tops_d1_32_b8_o2	999999	1	32	8	top-sites	1	0	${COVERAGE_PCT}	0,64	CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24
selection	perdepth	cov${COVERAGE_PCT}_perdepth_d4_24_b24_o2	999999	4	24	24	per-depth	1	0	${COVERAGE_PCT}	0,64	
selection	greedy	cov${COVERAGE_PCT}_greedy_d4_24_b8_o2	999999	4	24	8	greedy	1	10000	${COVERAGE_PCT}	0,64	
EOF
  fi
  python3 - "${VARIANTS_TSV}" "${METADATA_CSV}" <<'PY'
import csv
import sys

tsv, out = sys.argv[1:3]
fields = [
    "axis",
    "value",
    "name",
    "top_k",
    "depth_min",
    "depth",
    "site_budget",
    "selection_mode",
    "sites_per_depth",
    "candidate_pool",
    "target_coverage_pct",
    "prefetch_byte_offsets",
    "branch_depth_policy",
]
rows = []
idx = 0
for raw in open(tsv, encoding="utf-8"):
    raw = raw.rstrip("\n")
    if not raw or raw.startswith("#"):
        continue
    parts = raw.split("\t")
    if len(parts) < len(fields):
        parts += [""] * (len(fields) - len(parts))
    row = dict(zip(fields, parts))
    idx += 1
    row["variant"] = f"v{idx:02d}_{row['name']}"
    rows.append(row)
with open(out, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["variant"] + fields)
    writer.writeheader()
    writer.writerows(rows)
PY
}

build_one() {
  local variant="$1" name="$2" top_k="$3" depth_min="$4" depth="$5" site_budget="$6"
  local selection_mode="$7" sites_per_depth="$8" candidate_pool="$9" target_coverage_pct="${10}"
  local prefetch_byte_offsets="${11}" branch_depth_policy="${12}"
  local run_dir="${RUNS_DIR}/${variant}"
  local log_file="${RUNS_DIR}/${variant}.driver.log"

  log "build start ${variant}: d=${depth_min}-${depth} budget=${site_budget} mode=${selection_mode} offsets=${prefetch_byte_offsets} branch_policy=${branch_depth_policy:-default}"
  set +e
  RESULT_BASE="${RUNS_DIR}" \
  RUN_ID="${variant}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  TRACE_INPUT="${TRACE_INPUTS%%:*}" \
  BASELINE_BINARY="${BASELINE_BINARY}" \
  SOURCE_WORK="${SOURCE_WORK}" \
  CONFIG="${CONFIG}" \
  TOP_K="${top_k}" \
  TARGET_COVERAGE_PCT="${target_coverage_pct}" \
  DEPTH_MIN="${depth_min}" \
  DEPTH="${depth}" \
  SITE_BUDGET="${site_budget}" \
  CANDIDATE_POOL="${candidate_pool}" \
  SELECTION_MODE="${selection_mode}" \
  SITES_PER_DEPTH="${sites_per_depth}" \
  ALLOW_UNRESOLVED_TARGETS=1 \
  PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC}" \
  PREFETCH_BYTE_OFFSETS="${prefetch_byte_offsets}" \
  BRANCH_DEPTH_POLICY="${branch_depth_policy}" \
  PREFETCH_LABEL="${PREFETCH_LABEL}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  PROFILE_ITERATIONS="${PROFILE_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  OBJDUMP_BIN=llvm-objdump-19 \
  ADDR2LINE_BIN=llvm-addr2line-19 \
  RUN_BASELINE=0 \
  RUN_PROFILE=0 \
  RUN_TRACE=0 \
  CLEAN_WORKDIR=1 \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh" > "${log_file}" 2>&1
  local rc=$?
  set -e
  if [[ "${rc}" -eq 0 ]]; then
    append_status "${BUILD_STATUS_TSV}" "${variant}" "ok" "${rc}" "${run_dir}"
    log "build ok ${variant}"
  else
    append_status "${BUILD_STATUS_TSV}" "${variant}" "fail" "${rc}" "${run_dir}"
    log "build fail ${variant}: rc=${rc}; log=${log_file}"
  fi
}

wait_for_slot() {
  while (( "$(jobs -rp | wc -l)" >= PARALLEL_BUILDS )); do
    sleep 20
  done
}

run_parallel_builds() {
  : > "${BUILD_STATUS_TSV}"
  local idx=0
  while IFS=$'\t' read -r axis value name top_k depth_min depth site_budget selection_mode sites_per_depth candidate_pool target_coverage_pct prefetch_byte_offsets branch_depth_policy; do
    [[ -z "${axis:-}" || "${axis}" =~ ^# ]] && continue
    idx=$((idx + 1))
    local variant
    variant="$(printf 'v%02d_%s' "${idx}" "${name}")"
    wait_for_slot
    # Background workers must not inherit the variant-list file descriptor.
    # Some child commands can read stdin and corrupt the parent read loop.
    build_one "${variant}" "${name}" "${top_k}" "${depth_min}" "${depth}" "${site_budget}" \
      "${selection_mode}" "${sites_per_depth}" "${candidate_pool}" "${target_coverage_pct}" \
      "${prefetch_byte_offsets}" "${branch_depth_policy}" </dev/null &
  done < "${VARIANTS_TSV}"
  wait
}

summarize_fail() {
  local variant="$1" run_dir="$2" note="$3"
  python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
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

should_stop_after_profile() {
  [[ "${EARLY_STOP_WORSE_STREAK}" =~ ^[0-9]+$ && "${EARLY_STOP_WORSE_STREAK}" -gt 0 ]] || return 1
  python3 - "${OUT_DIR}/aggregate.csv" "${EARLY_STOP_WORSE_STREAK}" "${EARLY_STOP_WORSE_MARGIN_PCT}" <<'PY'
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
}

profile_successful_builds() {
  : > "${PROFILE_STATUS_TSV}"
  mapfile -t build_status_lines < <(sort -V "${BUILD_STATUS_TSV}")
  local line variant status rc run_dir
  local ok_profile_count=0
  for line in "${build_status_lines[@]}"; do
    IFS=$'\t' read -r variant status rc run_dir <<< "${line}"
    if [[ "${status}" != "ok" ]]; then
      summarize_fail "${variant}" "${run_dir}" "build_rc=${rc}"
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "skip_build_fail" "${rc}" "${run_dir}"
      continue
    fi
    local bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
    if [[ ! -x "${bin}" ]]; then
      summarize_fail "${variant}" "${run_dir}" "missing_binary_after_build"
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "fail" "missing_binary" "${run_dir}"
      continue
    fi
    log "profile start ${variant}: iterations=${PROFILE_ITERATIONS} core=${PROFILE_CORE}"
    set +e
    "${PROFILING_DIR}/run_detailed_profile.sh" \
      --workload verilator-qsort \
      --workload-name "${PREFETCH_LABEL}_qsort_${MAX_CYCLES}" \
      --sim-binary "${bin}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${PROFILE_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --perf-scope task \
      --results-base "${run_dir}/detailed_profile" \
      > "${run_dir}/profile_${PREFETCH_LABEL}.log" 2>&1 </dev/null
    local prc=$?
    set -e
    if [[ "${prc}" -ne 0 ]]; then
      summarize_fail "${variant}" "${run_dir}" "profile_rc=${prc}"
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "fail" "${prc}" "${run_dir}"
      log "profile fail ${variant}: rc=${prc}; log=${run_dir}/profile_${PREFETCH_LABEL}.log"
      continue
    fi
    python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
      --autotune-dir "${OUT_DIR}" \
      --variant "${variant}" \
      --run-dir "${run_dir}" \
      --baseline-summary "${BASELINE_SUMMARY}" \
      --max-cycles "${MAX_CYCLES}" \
      --status ok \
      --prefetch-label "${PREFETCH_LABEL}" \
      --rank-by "${SUMMARY_RANK_BY}"
    append_status "${PROFILE_STATUS_TSV}" "${variant}" "ok" "0" "${run_dir}"
    log "profile ok ${variant}"
    ok_profile_count=$((ok_profile_count + 1))
    if [[ "${PROFILE_VARIANT_LIMIT}" =~ ^[0-9]+$ && "${PROFILE_VARIANT_LIMIT}" -gt 0 && "${ok_profile_count}" -ge "${PROFILE_VARIANT_LIMIT}" ]]; then
      log "profile limit reached: PROFILE_VARIANT_LIMIT=${PROFILE_VARIANT_LIMIT}"
      break
    fi
    if should_stop_after_profile; then
      log "early-stop: last ${EARLY_STOP_WORSE_STREAK} successful profiled variants are worse than best runtime by >=${EARLY_STOP_WORSE_MARGIN_PCT}%"
      break
    fi
  done
}

write_reports() {
  python3 - "${OUT_DIR}/aggregate.csv" "${METADATA_CSV}" "${OUT_DIR}" "${MAX_CYCLES}" "${PREFETCH_LABEL}" <<'PY'
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

aggregate_path, metadata_path, out_dir, max_cycles, prefetch_label = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]
meta = {}
with metadata_path.open(newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        meta[row["variant"]] = row

def val(row, key):
    try:
        return float(row.get(key, "nan"))
    except ValueError:
        return float("nan")

def read_summary(run_dir):
    path = Path(run_dir) / "detailed_profile" / f"{prefetch_label}_qsort_{max_cycles}" / "summary.csv"
    out = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for item in csv.DictReader(f):
            try:
                out[item["metric"]] = float(item["mean"])
            except (KeyError, ValueError):
                continue
    return out

rows = []
if aggregate_path.exists():
    with aggregate_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "ok":
                continue
            row.update({f"meta_{k}": v for k, v in meta.get(row["variant"], {}).items()})
            metrics = read_summary(row.get("run_dir", ""))
            for key in ("l1i_mpki", "l2i_mpki", "instructions", "elapsed_sec"):
                if key in metrics:
                    row[key] = f"{metrics[key]:.6f}"
            rows.append(row)

rows.sort(key=lambda r: (val(r, "elapsed_delta_pct"), val(r, "l2i_mpki_delta_pct")))

leaderboard = out_dir / "runtime_leaderboard.md"
lines = [
    f"# {prefetch_label} Fixed-Coverage Runtime Leaderboard",
    "",
    "| Rank | Variant | Axis | Value | Runtime s | Runtime Delta % | L1I MPKI | L2I MPKI | L2I Delta % | Inst Delta % | Injected |",
    "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for idx, row in enumerate(rows, 1):
    lines.append(
        "| "
        f"{idx} | `{row.get('variant','')}` | "
        f"{row.get('meta_axis','')} | {row.get('meta_value','')} | "
        f"{val(row, 'elapsed_sec'):.3f} | {val(row, 'elapsed_delta_pct'):+.3f} | "
        f"{val(row, 'l1i_mpki'):.6f} | {val(row, 'l2i_mpki'):.6f} | "
        f"{val(row, 'l2i_mpki_delta_pct'):+.3f} | {val(row, 'instructions_delta_pct'):+.3f} | "
        f"{row.get('pass_injected','')} |"
    )
if rows:
    best = rows[0]
    lines += [
        "",
        "## Best Runtime",
        "",
        f"- Variant: `{best.get('variant','')}`",
        f"- Axis/value: `{best.get('meta_axis','')}` / `{best.get('meta_value','')}`",
        f"- Runtime delta: {val(best, 'elapsed_delta_pct'):+.3f}%",
        f"- L2I MPKI delta: {val(best, 'l2i_mpki_delta_pct'):+.3f}%",
        f"- Binary: `{best.get('binary','')}`",
    ]
    (out_dir / "best_runtime_variant.txt").write_text(
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
leaderboard.write_text("\n".join(lines) + "\n", encoding="utf-8")

effects_csv = out_dir / "parameter_effects.csv"
fields = [
    "axis",
    "value",
    "variant",
    "elapsed_sec",
    "elapsed_delta_pct",
    "l1i_mpki",
    "l2i_mpki",
    "l2i_mpki_delta_pct",
    "instructions_delta_pct",
    "pass_injected",
]
with effects_csv.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    for row in sorted(rows, key=lambda r: (r.get("meta_axis",""), r.get("meta_value",""))):
        writer.writerow(
            {
                "axis": row.get("meta_axis", ""),
                "value": row.get("meta_value", ""),
                "variant": row.get("variant", ""),
                "elapsed_sec": row.get("elapsed_sec", ""),
                "elapsed_delta_pct": row.get("elapsed_delta_pct", ""),
                "l1i_mpki": row.get("l1i_mpki", ""),
                "l2i_mpki": row.get("l2i_mpki", ""),
                "l2i_mpki_delta_pct": row.get("l2i_mpki_delta_pct", ""),
                "instructions_delta_pct": row.get("instructions_delta_pct", ""),
                "pass_injected": row.get("pass_injected", ""),
            }
        )

effect_md = out_dir / "parameter_effects.md"
md = ["# Fixed-Coverage Parameter Effects", ""]
by_axis = defaultdict(list)
for row in rows:
    by_axis[row.get("meta_axis", "")].append(row)
for axis in sorted(by_axis):
    items = sorted(by_axis[axis], key=lambda r: val(r, "elapsed_delta_pct"))
    md += [
        f"## {axis}",
        "",
        "| Value | Variant | Runtime Delta % | L2I Delta % | Inst Delta % | Injected |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in items:
        md.append(
            f"| {row.get('meta_value','')} | `{row.get('variant','')}` | "
            f"{val(row, 'elapsed_delta_pct'):+.3f} | {val(row, 'l2i_mpki_delta_pct'):+.3f} | "
            f"{val(row, 'instructions_delta_pct'):+.3f} | {row.get('pass_injected','')} |"
        )
    md.append("")
effect_md.write_text("\n".join(md), encoding="utf-8")

try:
    import matplotlib.pyplot as plt
except Exception:
    raise SystemExit(0)

plot_rows = [r for r in rows if r.get("meta_axis") != "baseline"]
fig, axes = plt.subplots(1, 3, figsize=(18, 5))
metrics = [
    ("elapsed_delta_pct", "Runtime Delta (%)"),
    ("l2i_mpki_delta_pct", "L2I MPKI Delta (%)"),
    ("instructions_delta_pct", "Instruction Delta (%)"),
]
for ax, (key, ylabel) in zip(axes, metrics):
    for axis in sorted({r.get("meta_axis","") for r in plot_rows}):
        items = [r for r in plot_rows if r.get("meta_axis") == axis]
        xs = list(range(len(items)))
        ys = [val(r, key) for r in items]
        labels = [r.get("meta_value", "") for r in items]
        ax.plot(xs, ys, marker="o", label=axis)
        for x, y, label in zip(xs, ys, labels):
            ax.annotate(label, (x, y), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=8)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel(ylabel)
    ax.set_xticks([])
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)
fig.suptitle("Fixed Coverage Parameter Effects")
fig.tight_layout()
fig.savefig(out_dir / "parameter_effects.png", dpi=180)
plt.close(fig)
PY
  log "runtime leaderboard: ${OUT_DIR}/runtime_leaderboard.md"
  log "parameter effects: ${OUT_DIR}/parameter_effects.md"
}

require_file "${BASELINE_BINARY}"
require_file "${BASELINE_SUMMARY}"
require_file "${BEST_PLAN}"
require_file "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh"
require_file "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py"
require_dir "${SOURCE_WORK}"

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
coverage_pct=${COVERAGE_PCT}
best_plan=${BEST_PLAN}
trace_inputs=${TRACE_INPUTS}
trace_input_count=${#trace_dirs[@]}
baseline_binary=${BASELINE_BINARY}
baseline_summary=${BASELINE_SUMMARY}
source_work=${SOURCE_WORK}
max_cycles=${MAX_CYCLES}
profile_core=${PROFILE_CORE}
profile_iterations=${PROFILE_ITERATIONS}
parallel_builds=${PARALLEL_BUILDS}
build_jobs=${BUILD_JOBS}
prefetch_mnemonic=${PREFETCH_MNEMONIC}
prefetch_label=${PREFETCH_LABEL}
summary_rank_by=${SUMMARY_RANK_BY}
variants_tsv_input=${VARIANTS_TSV_INPUT}
early_stop_worse_streak=${EARLY_STOP_WORSE_STREAK}
early_stop_worse_margin_pct=${EARLY_STOP_WORSE_MARGIN_PCT}
profile_variant_limit=${PROFILE_VARIANT_LIMIT}
EOF

log "fixed-coverage parallel sweep start: ${OUT_DIR}"
if [[ -n "${VARIANTS_TSV_INPUT}" ]]; then
  log "using custom variant TSV: ${VARIANTS_TSV_INPUT}"
else
  log "coverage fixed at ${COVERAGE_PCT}%"
fi
log "trace input count: ${#trace_dirs[@]}"
log "parallel builds=${PARALLEL_BUILDS}, build_jobs=${BUILD_JOBS}"
log "profile iterations=${PROFILE_ITERATIONS}; profiles run sequentially on core ${PROFILE_CORE}"
log "summary rank by=${SUMMARY_RANK_BY}; early-stop worse streak=${EARLY_STOP_WORSE_STREAK}; margin=${EARLY_STOP_WORSE_MARGIN_PCT}%"

run_parallel_builds
log "parallel build phase complete"
profile_successful_builds
log "profile phase complete"
write_reports
log "fixed-coverage parallel sweep done"
