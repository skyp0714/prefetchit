#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
STATIC_DIR="${REPO_ROOT}/static_cond_prefetch"
PROFILING_DIR="${REPO_ROOT}/profiling"

RUN_ID="${RUN_ID:-static_cond_autotune_$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/static_cond_autotune/${RUN_ID}}"
RUNS_DIR="${OUT_DIR}/runs"
LOG_DIR="${OUT_DIR}/logs"
CAND_DIR="${OUT_DIR}/candidates"
PLAN_DIR="${OUT_DIR}/plans"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-3}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PARALLEL_BUILDS="${PARALLEL_BUILDS:-4}"
BUILD_JOBS="${BUILD_JOBS:-8}"
FORCE_BUILD="${FORCE_BUILD:-0}"
FORCE_PROFILE="${FORCE_PROFILE:-0}"
PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC:-prefetcht1}"
BASE_BINARY="${BASE_BINARY:-${REPO_ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-${CONFIG}}"
TRACE_INPUTS="${TRACE_INPUTS:-${LLVM_PREFETCH_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace01/l2_miss:${LLVM_PREFETCH_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace02/l2_miss:${LLVM_PREFETCH_DIR}/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces/baseline_qsort_538240_trace03/l2_miss}"
EXISTING_COMPARE_DIR="${EXISTING_COMPARE_DIR:-${LLVM_PREFETCH_DIR}/results/cond_sampleip_compare/cond_sampleip_compare_20260628_014845}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv}"
BASELINE_PER_ITER="${BASELINE_PER_ITER:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/per_iteration.csv}"

mkdir -p "${OUT_DIR}" "${RUNS_DIR}" "${LOG_DIR}" "${CAND_DIR}" "${PLAN_DIR}"
LOG="${OUT_DIR}/run.log"
VARIANTS_TSV="${OUT_DIR}/static_variants.tsv"
BUILD_STATUS="${OUT_DIR}/build_status.tsv"
PROFILE_STATUS="${OUT_DIR}/profile_status.tsv"
SUMMARY_CSV="${OUT_DIR}/summary.csv"
SUMMARY_MD="${OUT_DIR}/summary.md"

log() { echo "[$(date '+%F %T')] $*" | tee -a "${LOG}"; }
require_file() { [[ -f "$1" ]] || { echo "[err] missing file: $1" | tee -a "${LOG}" >&2; exit 1; }; }
append_status() { local f="$1"; shift; { flock 9; local IFS=$'\t'; printf '%s\n' "$*"; } 9>"${f}.lock" >> "${f}"; }

require_file "${BASE_BINARY}"
require_file "${BASELINE_SUMMARY}"
require_file "${BASELINE_PER_ITER}"
require_file "${EXISTING_COMPARE_DIR}/summary.csv"

generate_candidates() {
  log "generate static candidate rankings"
  if [[ ! -s "${CAND_DIR}/static_cond_tail-sparse.csv" || ! -s "${CAND_DIR}/static_cond_entry-window.csv" || ! -s "${CAND_DIR}/static_cond_fetch-gap.csv" ]]; then
    local trace_args=()
    IFS=':' read -r -a trace_dirs <<< "${TRACE_INPUTS}"
    for trace_dir in "${trace_dirs[@]}"; do
      trace_args+=(--trace-dir "${trace_dir}")
    done
    python3 "${STATIC_DIR}/tools/sweep_static_cond_algorithms.py" \
      --binary "${BASE_BINARY}" \
      "${trace_args[@]}" \
      --out-dir "${OUT_DIR}/candidate_sweep" \
      --ks 10000,25000,50000,60000,75000,100000,125000,150000 \
      --target-k 100000 \
      --modes tail-sparse,entry-window,fetch-gap,sparse-hot,span,frontier,combined \
      --candidate-targets both \
      --target-window-lines 16 \
      --nm llvm-nm-19 \
      --objdump llvm-objdump-19 \
      >> "${LOG}" 2>&1
    cp "${OUT_DIR}/candidate_sweep/candidates"/static_cond_*.csv "${CAND_DIR}/"
  else
    log "candidate reuse existing CSVs in ${CAND_DIR}"
  fi

  local ens="${CAND_DIR}/static_cond_ensemble_rr.csv"
  if [[ ! -s "${ens}" ]]; then
    python3 "${STATIC_DIR}/tools/ensemble_cond_candidates.py" \
      --candidate-dir "${CAND_DIR}" \
      --out-csv "${ens}" \
      --stage tail-sparse:20000 \
      --stage entry-window:20000 \
      --round-robin tail-sparse,entry-window,fetch-gap,frontier \
      --round-robin-limit 60000 \
      --round-robin-chunk 8 \
      --tail-mode tail-sparse \
      --tail-mode entry-window \
      --tail-mode fetch-gap \
      --tail-mode span \
      --tail-mode frontier \
      --label ensemble_rr \
      >> "${LOG}" 2>&1
  fi
}

write_variants() {
  cat > "${VARIANTS_TSV}" <<EOF
variant	group	label	candidate	top_k	site_policy	prev_branches	site_budget	offsets	site_types	skip_same
static_ts100k_cur0_skip	static	Static tail-sparse 100k current skip-same	${CAND_DIR}/static_cond_tail-sparse.csv	100000	current	0	1	0	-	1
static_ts125k_cur0_skip	static	Static tail-sparse 125k current skip-same	${CAND_DIR}/static_cond_tail-sparse.csv	125000	current	0	1	0	-	1
static_ts60k_cur064_skip	static	Static tail-sparse 60k current 0+64 skip-same	${CAND_DIR}/static_cond_tail-sparse.csv	60000	current	0	1	0,64	-	1
static_ts75k_cur064_skip	static	Static tail-sparse 75k current 0+64 skip-same	${CAND_DIR}/static_cond_tail-sparse.csv	75000	current	0	1	0,64	-	1
static_entry100k_cur0_skip	static	Static entry-window 100k current skip-same	${CAND_DIR}/static_cond_entry-window.csv	100000	current	0	1	0	-	1
static_gap100k_cur0_skip	static	Static fetch-gap 100k current skip-same	${CAND_DIR}/static_cond_fetch-gap.csv	100000	current	0	1	0	-	1
static_ens100k_cur0_skip	static	Static ensemble 100k current skip-same	${CAND_DIR}/static_cond_ensemble_rr.csv	100000	current	0	1	0	-	1
static_ts75k_cprev1_cond0_skip	static	Static tail-sparse 75k current+prev1 COND skip-same	${CAND_DIR}/static_cond_tail-sparse.csv	75000	current-prev	1	2	0	COND	1
EOF
}

plan_one() {
  local variant="$1" label="$2" candidate="$3" top_k="$4" site_policy="$5" prev_branches="$6" site_budget="$7" offsets="$8" site_types="$9" skip_same="${10}"
  local plan="${PLAN_DIR}/${variant}.plan.json"
  if [[ -s "${plan}" ]]; then
    log "plan reuse ${variant}: ${plan}"
    return 0
  fi
  require_file "${candidate}"
  log "plan start ${variant}: top_k=${top_k} site=${site_policy} prev=${prev_branches} budget=${site_budget} offsets=${offsets} types=${site_types:-all} skip_same=${skip_same}"
  local args=(
    --binary "${BASE_BINARY}"
    --candidates "${candidate}"
    --output "${plan}"
    --top-k "${top_k}"
    --site-policy "${site_policy}"
    --prev-branches "${prev_branches}"
    --site-budget-per-target "${site_budget}"
    --prefetch-mnemonic "${PREFETCH_MNEMONIC}"
    --prefetch-byte-offsets "${offsets}"
    --label "${variant}"
    --nm llvm-nm-19
    --objdump llvm-objdump-19
    --addr2line llvm-addr2line-19
  )
  if [[ -n "${site_types}" && "${site_types}" != "-" ]]; then
    args+=(--site-branch-types "${site_types}")
  fi
  if [[ "${skip_same}" == "1" ]]; then
    args+=(--skip-same-cacheline-site-target)
  fi
  python3 "${STATIC_DIR}/tools/static_cond_candidates_to_plan.py" "${args[@]}" > "${LOG_DIR}/${variant}.plan.log" 2>&1
}

generate_plans() {
  log "generate prefetch plans"
  while IFS=$'\t' read -r variant group label candidate top_k site_policy prev_branches site_budget offsets site_types skip_same; do
    plan_one "${variant}" "${label}" "${candidate}" "${top_k}" "${site_policy}" "${prev_branches}" "${site_budget}" "${offsets}" "${site_types}" "${skip_same}"
  done < <(tail -n +2 "${VARIANTS_TSV}")
}

build_one() {
  local variant="$1"
  local plan="${PLAN_DIR}/${variant}.plan.json"
  local run_dir="${RUNS_DIR}/${variant}"
  local bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${variant}"
  local build_log="${LOG_DIR}/${variant}.build.log"
  if [[ "${FORCE_BUILD}" != "1" && -x "${bin}" ]]; then
    append_status "${BUILD_STATUS}" "${variant}" "ok" "0" "${run_dir}" "reuse"
    log "build reuse ${variant}"
    return 0
  fi
  require_file "${plan}"
  log "build start ${variant}: plan=${plan}"
  set +e
  RESULT_BASE="${RUNS_DIR}" \
  RUN_ID="${variant}" \
  TRACE_INPUTS="${TRACE_INPUTS}" \
  EXTERNAL_PLAN="${plan}" \
  PREFETCH_LABEL="${variant}" \
  PREFETCH_MNEMONIC="${PREFETCH_MNEMONIC}" \
  CONFIG="${CONFIG}" \
  MAX_CYCLES="${MAX_CYCLES}" \
  PROFILE_ITERATIONS="${PROFILE_ITERATIONS}" \
  PROFILE_CORE="${PROFILE_CORE}" \
  BUILD_JOBS="${BUILD_JOBS}" \
  RUN_BASELINE=0 RUN_PROFILE=0 RUN_TRACE=0 CLEAN_WORKDIR=1 \
  OBJDUMP_BIN=llvm-objdump-19 ADDR2LINE_BIN=llvm-addr2line-19 \
  bash "${LLVM_PREFETCH_DIR}/scripts/run_prefetcht1_l2_eval.sh" > "${build_log}" 2>&1
  local rc=$?
  set -e
  if [[ "${rc}" -eq 0 ]]; then
    append_status "${BUILD_STATUS}" "${variant}" "ok" "0" "${run_dir}" "built"
    log "build ok ${variant}"
  else
    append_status "${BUILD_STATUS}" "${variant}" "fail" "${rc}" "${run_dir}" "${build_log}"
    log "build fail ${variant}: rc=${rc}; log=${build_log}"
  fi
}

wait_for_slot() {
  while (( "$(jobs -rp | wc -l)" >= PARALLEL_BUILDS )); do
    wait -n || true
  done
}

run_builds() {
  : > "${BUILD_STATUS}"
  while IFS=$'\t' read -r variant _rest; do
    wait_for_slot
    build_one "${variant}" </dev/null &
  done < <(tail -n +2 "${VARIANTS_TSV}")
  wait
}

profile_builds() {
  : > "${PROFILE_STATUS}"
  sort -V "${BUILD_STATUS}" | while IFS=$'\t' read -r variant status rc run_dir note; do
    if [[ "${status}" != "ok" ]]; then
      append_status "${PROFILE_STATUS}" "${variant}" "skip_build_fail" "${rc}" "${run_dir}" "${note:-}"
      continue
    fi
    local bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${variant}"
    local per_iter="${run_dir}/detailed_profile/${variant}_qsort_${MAX_CYCLES}/per_iteration.csv"
    if [[ "${FORCE_PROFILE}" != "1" && -f "${per_iter}" ]]; then
      append_status "${PROFILE_STATUS}" "${variant}" "ok" "0" "${run_dir}" "reuse"
      log "profile reuse ${variant}"
      continue
    fi
    require_file "${bin}"
    log "profile start ${variant}: iterations=${PROFILE_ITERATIONS} core=${PROFILE_CORE}"
    set +e
    "${PROFILING_DIR}/run_detailed_profile.sh" \
      --workload verilator-qsort \
      --workload-name "${variant}_qsort_${MAX_CYCLES}" \
      --sim-binary "${bin}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${PROFILE_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --perf-scope task \
      --results-base "${run_dir}/detailed_profile" \
      > "${LOG_DIR}/${variant}.profile.log" 2>&1 </dev/null
    rc=$?
    set -e
    if [[ "${rc}" -eq 0 ]]; then
      append_status "${PROFILE_STATUS}" "${variant}" "ok" "0" "${run_dir}" "profiled"
      log "profile ok ${variant}"
    else
      append_status "${PROFILE_STATUS}" "${variant}" "fail" "${rc}" "${run_dir}" "${LOG_DIR}/${variant}.profile.log"
      log "profile fail ${variant}: rc=${rc}; log=${LOG_DIR}/${variant}.profile.log"
    fi
  done
}

summarize() {
  python3 - "${OUT_DIR}" "${VARIANTS_TSV}" "${EXISTING_COMPARE_DIR}/summary.csv" "${BASELINE_SUMMARY}" "${BASELINE_PER_ITER}" "${MAX_CYCLES}" <<'PY'
import csv, json, math, statistics, sys
from pathlib import Path

out=Path(sys.argv[1]); variants=Path(sys.argv[2]); existing=Path(sys.argv[3]); baseline_summary=Path(sys.argv[4]); baseline_per=Path(sys.argv[5]); max_cycles=sys.argv[6]

def read_metric_summary(path):
    return {r["metric"]: float(r["mean"]) for r in csv.DictReader(open(path, newline="", encoding="utf-8"))}

def read_per(path):
    rows=list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    vals=[float(r["elapsed_sec"]) for r in rows if r.get("elapsed_sec")]
    return len(vals), (statistics.mean(vals) if vals else 0.0), (statistics.stdev(vals) if len(vals)>1 else 0.0)

existing_rows=list(csv.DictReader(open(existing, newline="", encoding="utf-8")))
base=read_metric_summary(baseline_summary)
_, _, base_sd = read_per(baseline_per)
base_rt=base.get("elapsed_sec", 0.0)
rows=[]

for r in existing_rows:
    if r.get("status") != "ok":
        continue
    if r["variant"] == "baseline" or r["group"] == "pgo":
        rows.append(dict(r))
for r in existing_rows:
    if r.get("status") == "ok" and r["group"] == "static":
        rr=dict(r)
        rr["group"]="static-prev"
        rows.append(rr)

variant_meta={}
with variants.open(newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f, delimiter="\t"):
        variant_meta[r["variant"]]=r

for variant, meta in variant_meta.items():
    run_dir=out/"runs"/variant
    summary=run_dir/"detailed_profile"/f"{variant}_qsort_{max_cycles}"/"summary.csv"
    per=run_dir/"detailed_profile"/f"{variant}_qsort_{max_cycles}"/"per_iteration.csv"
    plan=out/"plans"/f"{variant}.plan.json"
    if not summary.exists():
        rows.append({
            "variant": variant, "group": "static-new", "label": meta["label"], "status": "missing_profile",
            "runtime_mean": "0", "runtime_stdev": "0", "l2i_mpki": "0", "l1i_mpki": "0",
            "instructions": "0", "speedup_pct": "0", "injections": "", "planned_prefetches": "",
        })
        continue
    s=read_metric_summary(summary); _, _, sd=read_per(per)
    st=json.load(open(plan)).get("stats", {}) if plan.exists() else {}
    rt=s.get("elapsed_sec", 0.0)
    rows.append({
        "variant": variant,
        "group": "static-new",
        "label": meta["label"],
        "status": "ok",
        "runtime_mean": rt,
        "runtime_stdev": sd,
        "l2i_mpki": s.get("l2i_mpki", 0.0),
        "l1i_mpki": s.get("l1i_mpki", 0.0),
        "instructions": s.get("instructions", 0.0),
        "speedup_pct": (base_rt / rt - 1.0) * 100.0 if rt else 0.0,
        "injections": st.get("selected_injections", ""),
        "planned_prefetches": st.get("planned_prefetches", ""),
    })

fields=["variant","group","label","status","runtime_mean","runtime_stdev","l2i_mpki","l1i_mpki","instructions","speedup_pct","injections","planned_prefetches"]
with (out/"summary.csv").open("w", newline="", encoding="utf-8") as f:
    w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def as_float(x):
    try: return float(x)
    except Exception: return 0.0

best=max((r for r in rows if r["status"]=="ok" and r["variant"]!="baseline"), key=lambda r: as_float(r["speedup_pct"]), default=None)
static_ok=[r for r in rows if r["status"]=="ok" and r["group"].startswith("static")]
static_sorted=sorted(static_ok, key=lambda r: as_float(r.get("injections", 0)))

lines=[
    "# Static COND Autotune Round",
    "",
    f"- Existing compare source: `{existing}`",
    f"- Baseline runtime: {base_rt:.3f}s",
    f"- Best variant: `{best['variant'] if best else 'none'}` ({as_float(best['speedup_pct']) if best else 0.0:.2f}% speedup)",
    "",
    "## Baseline And PGO COND",
    "",
    "| Variant | Runtime mean (s) | Runtime stdev | Speedup % | L2I MPKI | L1I MPKI | Instructions | Injections |",
    "|---|---:|---:|---:|---:|---:|---:|---:|",
]
for r in rows:
    if r["variant"]!="baseline" and r["group"]!="pgo":
        continue
    lines.append(f"| {r['label']} | {as_float(r['runtime_mean']):.3f} | {as_float(r['runtime_stdev']):.3f} | {as_float(r['speedup_pct']):.3f} | {as_float(r['l2i_mpki']):.3f} | {as_float(r['l1i_mpki']):.3f} | {as_float(r['instructions']):.0f} | {r['injections']} |")
lines += [
    "",
    "## Static Schemes Sorted By Injection Count",
    "",
    "| Variant | Group | Runtime mean (s) | Runtime stdev | Speedup % | L2I MPKI | L1I MPKI | Instructions | Injections | Planned prefetches |",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for r in static_sorted:
    lines.append(f"| {r['label']} | {r['group']} | {as_float(r['runtime_mean']):.3f} | {as_float(r['runtime_stdev']):.3f} | {as_float(r['speedup_pct']):.3f} | {as_float(r['l2i_mpki']):.3f} | {as_float(r['l1i_mpki']):.3f} | {as_float(r['instructions']):.0f} | {r['injections']} | {r['planned_prefetches']} |")

bad=[r for r in rows if r["status"]=="ok" and (as_float(r["runtime_mean"])<=0 or as_float(r["l2i_mpki"])<=0 or as_float(r["instructions"])<=0)]
lines += ["", "## Validation", ""]
lines.append(f"- Zero/NaN metric rows among ok results: {len(bad)}")
if bad:
    lines.extend(f"- `{r['variant']}` has invalid metric(s)" for r in bad)

(out/"summary.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
print("\n".join(lines))

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pgo=[r for r in rows if r["group"]=="pgo"]
    static=static_sorted
    plot_rows=[next(r for r in rows if r["variant"]=="baseline")] + pgo + static
    labels=[r["label"].replace("Static ","S ").replace("PGO COND ","PGO ") for r in plot_rows]
    x=list(range(len(plot_rows)))
    runtimes=[as_float(r["runtime_mean"]) for r in plot_rows]
    l2=[as_float(r["l2i_mpki"]) for r in plot_rows]
    fig, ax1=plt.subplots(figsize=(max(12, len(plot_rows)*0.75), 6))
    ax1.bar(x, runtimes, color="#4c78a8", alpha=0.75, label="Runtime")
    ax1.set_ylabel("Runtime (s)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=40, ha="right")
    ax2=ax1.twinx()
    ax2.plot(x, l2, color="#f58518", marker="o", linewidth=2.0, label="L2I MPKI")
    ax2.set_ylabel("L2I MPKI")
    ax1.set_title("Static COND Prefetch Autotune")
    fig.tight_layout()
    fig.savefig(out/"runtime_l2i_compare.png", dpi=180)
except Exception as exc:
    (out/"plot_error.txt").write_text(str(exc)+"\n", encoding="utf-8")
PY
}

cat > "${OUT_DIR}/manifest.txt" <<EOF
run_id=${RUN_ID}
out_dir=${OUT_DIR}
base_binary=${BASE_BINARY}
existing_compare_dir=${EXISTING_COMPARE_DIR}
max_cycles=${MAX_CYCLES}
profile_iterations=${PROFILE_ITERATIONS}
profile_core=${PROFILE_CORE}
parallel_builds=${PARALLEL_BUILDS}
build_jobs=${BUILD_JOBS}
prefetch_mnemonic=${PREFETCH_MNEMONIC}
candidate_targets=both
target_window_lines=16
EOF

log "start static cond autotune round: ${OUT_DIR}"
generate_candidates
write_variants
generate_plans
run_builds
profile_builds
summarize | tee -a "${LOG}"
ln -sfn "${OUT_DIR}" "${LLVM_PREFETCH_DIR}/results/static_cond_autotune/latest"
log "done"
