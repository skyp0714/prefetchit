#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${PROFILING_DIR}/.." && pwd)"

MANIFEST="${MANIFEST:-${PROFILING_DIR}/results/prefetchit_builds_dtcov_v1/latest_manifest_with_baseline.csv}"
BUILD_ROOT="${BUILD_ROOT:-${PROFILING_DIR}/results/prefetchit_builds_dtcov_v1}"
INJECTION_ROOT="${INJECTION_ROOT:-${PROFILING_DIR}/results/prefetch_dtcov_variants_v1}"
EVAL_BASE="${EVAL_BASE:-${PROFILING_DIR}/results/prefetchit_eval_dtcov_v1}"
DETAILED_BASE="${DETAILED_BASE:-${PROFILING_DIR}/results/detailed_profile_prefetch_dtcov_v1}"
RUNTIME_BASE="${RUNTIME_BASE:-${PROFILING_DIR}/results/runtime_only_prefetch_dtcov_v1}"
TRACE_BASE="${TRACE_BASE:-${PROFILING_DIR}/results/trace_dtcov_v1}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-3}"
RUNTIME_ITERATIONS="${RUNTIME_ITERATIONS:-3}"
PROFILE_CORE="${PROFILE_CORE:-0}"
TRACE_DURATION_SEC="${TRACE_DURATION_SEC:-60}"
TRACE_SAMPLE_PERIOD="${TRACE_SAMPLE_PERIOD:-127}"
POLL_SEC="${POLL_SEC:-300}"

mkdir -p "${EVAL_BASE}" "${DETAILED_BASE}" "${RUNTIME_BASE}" "${TRACE_BASE}"

echo "[phase] detailed/runtime evaluation"
"${SCRIPT_DIR}/run_prefetchit_eval_pipeline.sh" \
  --manifest "${MANIFEST}" \
  --build-root "${BUILD_ROOT}" \
  --workload verilator-qsort \
  --max-cycles "${MAX_CYCLES}" \
  --profile-iterations "${PROFILE_ITERATIONS}" \
  --runtime-iterations "${RUNTIME_ITERATIONS}" \
  --profile-core "${PROFILE_CORE}" \
  --poll-sec "${POLL_SEC}" \
  --eval-base "${EVAL_BASE}" \
  --detailed-base "${DETAILED_BASE}" \
  --runtime-base "${RUNTIME_BASE}" \
  --injection-root "${INJECTION_ROOT}"

eval_dir="$(ls -1dt "${EVAL_BASE}"/* 2>/dev/null | head -n 1)"
if [[ -z "${eval_dir}" || ! -d "${eval_dir}" ]]; then
  echo "[err] failed to locate eval output under ${EVAL_BASE}" >&2
  exit 1
fi
echo "[ok] eval_dir=${eval_dir}"

echo "[phase] optimized L2 PEBS+LBR traces"
trace_log="${eval_dir}/optimized_trace_runs.log"
: > "${trace_log}"

tail -n +2 "${MANIFEST}" | while IFS=, read -r variant vp session vdir delay log_path bin_out; do
  if [[ "${variant}" == "baseline" ]]; then
    echo "[skip] baseline trace: reusing existing baseline trace unless explicitly rerun" | tee -a "${trace_log}"
    continue
  fi
  bin_out="${bin_out%\"}"
  bin_out="${bin_out#\"}"
  wl_name="qsort_${MAX_CYCLES}_${vp}"
  echo "[run] L2 trace ${variant} ${bin_out}" | tee -a "${trace_log}"
  "${PROFILING_DIR}/run_pebs_sampling.sh" \
    --workload verilator-qsort \
    --workload-name "${wl_name}" \
    --sim-binary "${bin_out}" \
    --max-cycles "${MAX_CYCLES}" \
    --profile-core "${PROFILE_CORE}" \
    --duration-sec "${TRACE_DURATION_SEC}" \
    --sample-period "${TRACE_SAMPLE_PERIOD}" \
    --trace-mode split \
    --trace-select l2 \
    --run-analyze 1 \
    --results-base "${TRACE_BASE}" \
    >> "${trace_log}" 2>&1
done

echo "[phase] trace summary"
python3 - <<'PY' "${MANIFEST}" "${TRACE_BASE}" "${MAX_CYCLES}" "${eval_dir}"
import csv
import sys
from pathlib import Path

manifest, trace_base, max_cycles, eval_dir = sys.argv[1:5]
trace_base = Path(trace_base)
eval_dir = Path(eval_dir)
rows = list(csv.DictReader(open(manifest, newline="", encoding="utf-8")))

out = []
out.append("# DTCOV Optimized L2 Trace Summary")
out.append("")
for row in rows:
    variant = row["variant"]
    if variant == "baseline":
        continue
    vp = row["variant_prefixed"]
    trace_dir = trace_base / f"qsort_{max_cycles}_{vp}" / "l2_miss"
    summary = trace_dir / "trace_summary.md"
    target_csv = trace_dir / "target_branch_counts.csv"
    out.append(f"## {variant}")
    out.append(f"- trace_dir: `{trace_dir}`")
    if summary.exists():
        text = summary.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in text[:12]:
            if line.strip():
                out.append(f"- {line.lstrip('- ').strip()}")
    if target_csv.exists():
        out.append("")
        out.append("| Rank | Symbol | SrcLine | Branch | Samples |")
        out.append("|---:|---|---|---|---:|")
        with target_csv.open(newline="", encoding="utf-8") as f:
            for idx, r in enumerate(csv.DictReader(f), start=1):
                if idx > 15:
                    break
                out.append(
                    f"| {idx} | {r.get('symbol','')} | {r.get('srcline','')} | "
                    f"{r.get('branch_type','')} | {r.get('count','')} |"
                )
    out.append("")

(eval_dir / "optimized_l2_trace_summary.md").write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY

echo "[ok] wrote ${eval_dir}/optimized_l2_trace_summary.md"
