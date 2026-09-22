#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <fixedcov-run-dir>" >&2
  exit 1
fi

OUT_DIR="$(cd "$1" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLVM_PREFETCH_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${LLVM_PREFETCH_DIR}/.." && pwd)"
PROFILING_DIR="${REPO_ROOT}/profiling"

MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_CORE="${PROFILE_CORE:-0}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-3}"
CONFIG="${CONFIG:-DualMegaBoomAndSingleRocketConfig}"
PREFETCH_LABEL="${PREFETCH_LABEL:-prefetcht1}"
BASELINE_SUMMARY="${BASELINE_SUMMARY:-${LLVM_PREFETCH_DIR}/results/prefetch_plateau/resume_aggressive_20260620_105007/exact_best_compare/final_compare/profiles/baseline_qsort_${MAX_CYCLES}/summary.csv}"

BUILD_STATUS_TSV="${OUT_DIR}/build_status.tsv"
PROFILE_STATUS_TSV="${OUT_DIR}/profile_status.tsv"
REPAIR_LOG="${OUT_DIR}/repair_profiles.log"

log() {
  echo "[$(date '+%F %T')] $*" | tee -a "${REPAIR_LOG}"
}

require_file() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    echo "[err] missing file: ${path}" | tee -a "${REPAIR_LOG}" >&2
    exit 1
  fi
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

summarize_ok() {
  local variant="$1" run_dir="$2"
  python3 "${LLVM_PREFETCH_DIR}/tools/summarize_prefetcht1_autotune.py" \
    --autotune-dir "${OUT_DIR}" \
    --variant "${variant}" \
    --run-dir "${run_dir}" \
    --baseline-summary "${BASELINE_SUMMARY}" \
    --max-cycles "${MAX_CYCLES}" \
    --status ok
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
    --note "${note}" || true
}

rewrite_reports() {
  python3 - "${OUT_DIR}/aggregate.csv" "${OUT_DIR}/variant_metadata.csv" "${OUT_DIR}" "${MAX_CYCLES}" <<'PY'
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path

aggregate_path, metadata_path, out_dir, max_cycles = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
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
    path = Path(run_dir) / "detailed_profile" / f"prefetcht1_qsort_{max_cycles}" / "summary.csv"
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
            if row.get("variant") not in meta:
                continue
            row.update({f"meta_{k}": v for k, v in meta[row["variant"]].items()})
            metrics = read_summary(row.get("run_dir", ""))
            for key in ("l1i_mpki", "l2i_mpki", "instructions", "elapsed_sec"):
                if key in metrics:
                    row[key] = f"{metrics[key]:.6f}"
            rows.append(row)

rows.sort(key=lambda r: (val(r, "elapsed_delta_pct"), val(r, "l2i_mpki_delta_pct")))

leaderboard = out_dir / "runtime_leaderboard.md"
lines = [
    "# Fixed-Coverage Runtime Leaderboard",
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

with (out_dir / "parameter_effects.csv").open("w", newline="", encoding="utf-8") as f:
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
(out_dir / "parameter_effects.md").write_text("\n".join(md), encoding="utf-8")
PY
}

require_file "${BUILD_STATUS_TSV}"
require_file "${BASELINE_SUMMARY}"

cp -f "${OUT_DIR}/aggregate.csv" "${OUT_DIR}/aggregate.before_repair.csv" 2>/dev/null || true
cp -f "${PROFILE_STATUS_TSV}" "${OUT_DIR}/profile_status.before_repair.tsv" 2>/dev/null || true
rm -f "${OUT_DIR}/aggregate.csv" "${OUT_DIR}/leaderboard.md" "${OUT_DIR}/best_variant.txt"
: > "${PROFILE_STATUS_TSV}"

log "repair fixedcov profiles start: ${OUT_DIR}"
mapfile -t build_status_lines < <(sort -V "${BUILD_STATUS_TSV}")
for line in "${build_status_lines[@]}"; do
  IFS=$'\t' read -r variant status rc run_dir <<< "${line}"
  if [[ "${status}" != "ok" ]]; then
    summarize_fail "${variant}" "${run_dir}" "build_rc=${rc}"
    append_status "${PROFILE_STATUS_TSV}" "${variant}" "skip_build_fail" "${rc}" "${run_dir}"
    continue
  fi
  bin="${run_dir}/bin/simulator-chipyard.harness-${CONFIG}-llvm-${PREFETCH_LABEL}"
  summary="${run_dir}/detailed_profile/${PREFETCH_LABEL}_qsort_${MAX_CYCLES}/summary.csv"
  if [[ ! -x "${bin}" ]]; then
    summarize_fail "${variant}" "${run_dir}" "missing_binary_after_build"
    append_status "${PROFILE_STATUS_TSV}" "${variant}" "fail" "missing_binary" "${run_dir}"
    continue
  fi
  if [[ ! -f "${summary}" ]]; then
    log "profile missing ${variant}: iterations=${PROFILE_ITERATIONS} core=${PROFILE_CORE}"
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
      > "${run_dir}/profile_${PREFETCH_LABEL}.repair.log" 2>&1 </dev/null
    prc=$?
    set -e
    if [[ "${prc}" -ne 0 ]]; then
      summarize_fail "${variant}" "${run_dir}" "profile_rc=${prc}"
      append_status "${PROFILE_STATUS_TSV}" "${variant}" "fail" "${prc}" "${run_dir}"
      log "profile fail ${variant}: rc=${prc}"
      continue
    fi
  else
    log "profile already present ${variant}"
  fi
  summarize_ok "${variant}" "${run_dir}"
  append_status "${PROFILE_STATUS_TSV}" "${variant}" "ok" "0" "${run_dir}"
  log "profile ok ${variant}"
done
rewrite_reports
log "repair fixedcov profiles done"
