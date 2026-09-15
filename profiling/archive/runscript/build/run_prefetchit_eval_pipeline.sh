#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "$0")" && pwd)/../bench/bench_common.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

BUILD_ROOT="${BUILD_ROOT:-${PROFILING_DIR}/results/prefetchit_builds}"
MANIFEST="${MANIFEST:-}"
WORKLOAD="${WORKLOAD:-verilator-qsort}"
MAX_CYCLES="${MAX_CYCLES:-538240}"
PROFILE_ITERATIONS="${PROFILE_ITERATIONS:-5}"
RUNTIME_ITERATIONS="${RUNTIME_ITERATIONS:-5}"
PROFILE_CORE="${PROFILE_CORE:-0}"
POLL_SEC="${POLL_SEC:-300}"
CHIPYARD_CONFIG="${CHIPYARD_CONFIG:-DualMegaBoomAndSingleRocketConfig}"
SKIP_EXISTING="${SKIP_EXISTING:-0}"

EVAL_BASE="${EVAL_BASE:-${PROFILING_DIR}/results/prefetchit_eval}"
DETAILED_BASE="${DETAILED_BASE:-${PROFILING_DIR}/results/detailed_profile_prefetchit}"
RUNTIME_BASE="${RUNTIME_BASE:-${PROFILING_DIR}/results/runtime_only_prefetchit}"
INJECTION_ROOT="${INJECTION_ROOT:-${PROFILING_DIR}/results/prefetchit_variants}"
LLVM_OBJDUMP="${LLVM_OBJDUMP:-llvm-objdump-19}"

usage() {
  cat <<'USAGE'
Usage: run_prefetchit_eval_pipeline.sh [options]

Options:
  --manifest <path>               Build launch manifest CSV. Default: latest in results/prefetchit_builds
  --build-root <path>             Build root containing logs/binaries/manifests
  --workload <name>               Workload for profile runs (default: verilator-qsort)
  --max-cycles <N>                +max-cycles for simulator (default: 538240)
  --profile-iterations <N>        Detailed profile iterations (default: 5)
  --runtime-iterations <N>        Runtime-only iterations (default: 5)
  --profile-core <N>              taskset core (default: 0)
  --poll-sec <N>                  Poll interval while waiting for build outputs (default: 300)
  --chipyard-config <Config>      Chipyard config name (default: DualMegaBoomAndSingleRocketConfig)
  --skip-existing                 Reuse existing detailed/runtime summaries instead of rerunning them
  --eval-base <path>              Root directory for evaluation artifacts
  --detailed-base <path>          Base directory for detailed profile outputs
  --runtime-base <path>           Base directory for runtime-only outputs
  --injection-root <path>         Directory containing injection summary csv files
  --llvm-objdump <path/bin>       llvm-objdump binary (default: llvm-objdump-19)
  -h, --help                      Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      MANIFEST="${2:-}"
      shift 2
      ;;
    --build-root)
      BUILD_ROOT="${2:-}"
      shift 2
      ;;
    --workload)
      WORKLOAD="${2:-}"
      shift 2
      ;;
    --max-cycles)
      MAX_CYCLES="${2:-}"
      shift 2
      ;;
    --profile-iterations)
      PROFILE_ITERATIONS="${2:-}"
      shift 2
      ;;
    --runtime-iterations)
      RUNTIME_ITERATIONS="${2:-}"
      shift 2
      ;;
    --profile-core)
      PROFILE_CORE="${2:-}"
      shift 2
      ;;
    --poll-sec)
      POLL_SEC="${2:-}"
      shift 2
      ;;
    --chipyard-config)
      CHIPYARD_CONFIG="${2:-}"
      shift 2
      ;;
    --skip-existing)
      SKIP_EXISTING=1
      shift
      ;;
    --eval-base)
      EVAL_BASE="${2:-}"
      shift 2
      ;;
    --detailed-base)
      DETAILED_BASE="${2:-}"
      shift 2
      ;;
    --runtime-base)
      RUNTIME_BASE="${2:-}"
      shift 2
      ;;
    --injection-root)
      INJECTION_ROOT="${2:-}"
      shift 2
      ;;
    --llvm-objdump)
      LLVM_OBJDUMP="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[err] unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! [[ "${MAX_CYCLES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --max-cycles must be a positive integer" >&2
  exit 1
fi
if ! [[ "${PROFILE_ITERATIONS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --profile-iterations must be a positive integer" >&2
  exit 1
fi
if ! [[ "${RUNTIME_ITERATIONS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --runtime-iterations must be a positive integer" >&2
  exit 1
fi
if ! [[ "${PROFILE_CORE}" =~ ^[0-9]+$ ]]; then
  echo "[err] --profile-core must be a non-negative integer" >&2
  exit 1
fi
if ! [[ "${POLL_SEC}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --poll-sec must be a positive integer" >&2
  exit 1
fi

if [[ -z "${MANIFEST}" ]]; then
  MANIFEST="$(ls -1t "${BUILD_ROOT}"/build_launch_manifest_*.csv 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "${MANIFEST}" || ! -f "${MANIFEST}" ]]; then
  echo "[err] build manifest not found. pass --manifest or ensure ${BUILD_ROOT}/build_launch_manifest_*.csv exists" >&2
  exit 1
fi

if ! command -v "${LLVM_OBJDUMP}" >/dev/null 2>&1; then
  echo "[err] llvm-objdump not found: ${LLVM_OBJDUMP}" >&2
  exit 1
fi

setup_verilator_env
require_chipyard_tree

TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${EVAL_BASE}/${TS}"
mkdir -p "${OUT_DIR}"
cp -f "${MANIFEST}" "${OUT_DIR}/build_manifest.csv"

if [[ -f "${INJECTION_ROOT}/injection_counts_by_depth.csv" ]]; then
  cp -f "${INJECTION_ROOT}/injection_counts_by_depth.csv" "${OUT_DIR}/injection_counts_by_depth.csv"
fi
if [[ -f "${INJECTION_ROOT}/injection_points_by_depth.csv" ]]; then
  cp -f "${INJECTION_ROOT}/injection_points_by_depth.csv" "${OUT_DIR}/injection_points_by_depth.csv"
fi
if [[ -f "${INJECTION_ROOT}/injection_summary.md" ]]; then
  cp -f "${INJECTION_ROOT}/injection_summary.md" "${OUT_DIR}/injection_summary.md"
fi
if [[ -f "${INJECTION_ROOT}/target_labels.csv" ]]; then
  cp -f "${INJECTION_ROOT}/target_labels.csv" "${OUT_DIR}/target_labels.csv"
fi

echo "[inf] manifest=${MANIFEST}"
echo "[inf] out_dir=${OUT_DIR}"
echo "[inf] workload=${WORKLOAD} max_cycles=${MAX_CYCLES}"

# Collect rows first for stable iteration order.
rows_tsv="${OUT_DIR}/manifest_rows.tsv"
tail -n +2 "${MANIFEST}" | awk -F, 'NF>=7 {print $1"\t"$2"\t"$3"\t"$4"\t"$5"\t"$6"\t"$7}' > "${rows_tsv}"
if [[ ! -s "${rows_tsv}" ]]; then
  echo "[err] no rows parsed from manifest: ${MANIFEST}" >&2
  exit 1
fi

wait_log="${OUT_DIR}/build_wait_status.log"
: > "${wait_log}"

echo "[phase] wait for staged builds to finish"
while IFS=$'\t' read -r variant vp session vdir delay log_path bin_out; do
  echo "[wait] variant=${vp} session=${session} binary=${bin_out}"
  while true; do
    now="$(date '+%F %T')"
    if [[ -s "${bin_out}" ]]; then
      echo "${now} [ok] ${vp} binary ready: ${bin_out}" | tee -a "${wait_log}"
      break
    fi

    if [[ -f "${log_path}" ]] && rg -n "^make(\[[0-9]+\])?: \*\*\*" "${log_path}" >/dev/null 2>&1; then
      echo "${now} [err] ${vp} build failed (make error in log): ${log_path}" | tee -a "${wait_log}" >&2
      exit 1
    fi

    if ! tmux has-session -t "${session}" 2>/dev/null; then
      if [[ -f "${log_path}" ]] && rg -n "\[ok\] variant=${vp} done=" "${log_path}" >/dev/null 2>&1; then
        # Session exited after successful completion but binary copy may race FS cache.
        sleep 5
        continue
      fi
      echo "${now} [err] session ended before binary was created: ${session}" | tee -a "${wait_log}" >&2
      [[ -f "${log_path}" ]] && tail -n 80 "${log_path}" | sed 's/^/[log] /' >&2
      exit 1
    fi

    echo "${now} [inf] waiting ${vp}: binary not ready yet" | tee -a "${wait_log}"
    sleep "${POLL_SEC}"
  done
done < "${rows_tsv}"

echo "[phase] debug/symbol checks"
DEBUG_CSV="${OUT_DIR}/binary_debug_check.csv"
echo "variant,variant_prefixed,binary,symbol_text_count,text_bytes,text_mib,nm_head_file" > "${DEBUG_CSV}"

while IFS=$'\t' read -r variant vp session vdir delay log_path bin_out; do
  nm_head="${OUT_DIR}/nm_${vp}.head20.txt"
  nm -C "${bin_out}" 2>/dev/null | head -n 20 > "${nm_head}" || true

  sym_count="$(nm -C --defined-only "${bin_out}" 2>/dev/null | awk '$2 ~ /[Tt]/ {c++} END {print c+0}')"

  text_hex="$(objdump -h "${bin_out}" 2>/dev/null | awk '$2==".text" {text=$3} END {print text}')"
  text_bytes="0"
  if [[ -n "${text_hex}" ]]; then
    text_bytes="$((16#${text_hex}))"
  fi
  text_mib="$(awk "BEGIN { printf \"%.3f\", ${text_bytes}/1048576 }")"

  if [[ "${sym_count}" -eq 0 ]]; then
    echo "[err] ${vp}: no text symbols found in nm output" >&2
    exit 1
  fi

  printf '%s,%s,"%s",%s,%s,%s,"%s"\n' \
    "${variant}" "${vp}" "${bin_out}" "${sym_count}" "${text_bytes}" "${text_mib}" "${nm_head}" \
    >> "${DEBUG_CSV}"
done < "${rows_tsv}"

echo "[phase] prefetchit assembly checks"
ASM_CSV="${OUT_DIR}/prefetch_asm_check.csv"
echo "variant,variant_prefixed,binary,prefetch_src_count,prefetch_objdump_count,status,disasm_snippet" > "${ASM_CSV}"

while IFS=$'\t' read -r variant vp session vdir delay log_path bin_out; do
  src_count="0"
  if [[ -d "${vdir}/generated-src" ]]; then
    src_count="$({ rg -uuu -o "prefetchit0|prefetcht0" "${vdir}/generated-src" 2>/dev/null || true; } | wc -l | tr -d ' ')"
  fi

  snippet="${OUT_DIR}/disasm_${vp}_prefetch.txt"
  pref_count="0"
  set +e
  "${LLVM_OBJDUMP}" -d "${bin_out}" 2>/dev/null \
    | rg -n '^[[:space:]]*([0-9]+:)?[[:space:]]*[0-9A-Fa-f]+:[[:space:]].*\bprefetch(it[01]|t[012])\b' \
    > "${snippet}"
  rc=$?
  set -e
  if [[ "${rc}" -eq 0 ]]; then
    pref_count="$(wc -l < "${snippet}" | tr -d ' ')"
  else
    : > "${snippet}"
  fi

  status="ok"
  if [[ "${variant}" == "baseline" ]]; then
    if [[ "${pref_count}" -ne 0 ]]; then
      status="unexpected_prefetch_in_baseline"
    fi
  else
    if [[ "${src_count}" -le 0 ]]; then
      status="missing_prefetch_in_source"
    elif [[ "${pref_count}" -le 0 ]]; then
      status="missing_prefetch_in_binary"
    fi
  fi

  printf '%s,%s,"%s",%s,%s,%s,"%s"\n' \
    "${variant}" "${vp}" "${bin_out}" "${src_count}" "${pref_count}" "${status}" "${snippet}" >> "${ASM_CSV}"

done < "${rows_tsv}"

if rg -n "unexpected_prefetch_in_baseline|missing_prefetch_in_source|missing_prefetch_in_binary" "${ASM_CSV}" >/dev/null 2>&1; then
  echo "[err] prefetchit assembly validation failed. See ${ASM_CSV}" >&2
  exit 1
fi

echo "[phase] prefetchit PC-relative checks"
PCREL_CSV="${OUT_DIR}/prefetch_pcrel_validation.csv"
python3 - <<'PY' "${ASM_CSV}" "${PCREL_CSV}"
import csv
import re
import sys
from pathlib import Path

asm_csv = Path(sys.argv[1])
out_csv = Path(sys.argv[2])

# Example lines:
# 117:    1154: 0f 18 3d e5 ff ff ff          prefetchit0 -0x1b(%rip)     # 0x1140 <foo>
# 118:    115b: 0f 18 0d e5 ff ff ff          prefetcht0 -0x1b(%rip)     # 0x1147 <__pf_target_x+0x40>
line_re = re.compile(
    r"^\s*(?:\d+:)?\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}\s+)+)\s+(prefetch(?:it[01]|t[012]))\s+([+-]?(?:0x[0-9a-fA-F]+|\d+))\(%rip\)\s+#\s+0x([0-9a-fA-F]+)(?:\s+<([^>]+)>)?"
)

rows = []
with asm_csv.open(newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

out_rows = []
failed = False

for row in rows:
    variant = row["variant"]
    vp = row["variant_prefixed"]
    snippet = Path(row["disasm_snippet"])
    pref_cnt = int(row["prefetch_objdump_count"])
    src_cnt = int(row["prefetch_src_count"])

    parsed = 0
    pass_cnt = 0
    fail_cnt = 0
    label_match_cnt = 0
    label_miss_cnt = 0
    unparsed_lines = 0
    mismatch_examples = []
    label_examples = []

    label_targets = set()
    try:
        import subprocess

        nm_out = subprocess.run(
            ["nm", "-an", row["binary"]],
            text=True,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        ).stdout.splitlines()
        for nm_ln in nm_out:
            parts = nm_ln.split()
            if len(parts) >= 3 and parts[2].startswith("__pf_target_"):
                base = int(parts[0], 16)
                # Multiline variants use label + 64*N. Keep this wider than
                # current sweeps so validation remains stable as line count changes.
                for off in range(0, 64 * 33, 64):
                    label_targets.add(base + off)
    except Exception:
        label_targets = set()

    if snippet.exists():
        for ln in snippet.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "prefetch" not in ln:
                continue
            m = line_re.match(ln)
            if not m:
                unparsed_lines += 1
                continue
            parsed += 1
            insn_addr = int(m.group(1), 16)
            instr_len = len(m.group(2).split())
            disp = int(m.group(4), 0)
            target_addr = int(m.group(5), 16)
            calc = (insn_addr + instr_len + disp) & ((1 << 64) - 1)
            if calc == target_addr:
                pass_cnt += 1
            else:
                fail_cnt += 1
                if len(mismatch_examples) < 5:
                    mismatch_examples.append(
                        f"insn=0x{insn_addr:x} len={instr_len} disp={disp} calc=0x{calc:x} target=0x{target_addr:x}"
                    )
            if label_targets:
                if target_addr in label_targets:
                    label_match_cnt += 1
                else:
                    label_miss_cnt += 1
                    if len(label_examples) < 5:
                        label_examples.append(f"target=0x{target_addr:x}")

    status = "ok"
    reason = ""
    if variant == "baseline":
        if pref_cnt != 0:
            status = "fail"
            reason = "baseline_has_prefetchit"
    else:
        if src_cnt <= 0 or pref_cnt <= 0:
            status = "fail"
            reason = "missing_prefetchit"
        elif parsed <= 0:
            status = "fail"
            reason = "no_parsed_prefetchit_lines"
        elif fail_cnt > 0:
            status = "fail"
            reason = "pcrel_mismatch"
        elif label_targets and label_miss_cnt > 0:
            # Newer dt coverage variants may legally use direct symbol+offset
            # operands for line-0/unresolved targets that cannot receive a
            # source label. Keep the strict PC-relative check above, but do not
            # fail solely because a subset of prefetches does not target a
            # __pf_target_* label.
            status = "warn"
            reason = "some_prefetch_targets_are_not_labels"
        elif unparsed_lines > 0:
            status = "warn"
            reason = "some_lines_unparsed"

    if status == "fail":
        failed = True

    out_rows.append(
        {
            "variant": variant,
            "variant_prefixed": vp,
            "prefetch_src_count": src_cnt,
            "prefetch_objdump_count": pref_cnt,
            "parsed_prefetch_lines": parsed,
            "pcrel_pass_count": pass_cnt,
            "pcrel_fail_count": fail_cnt,
            "label_target_pass_count": label_match_cnt,
            "label_target_fail_count": label_miss_cnt,
            "unparsed_prefetch_lines": unparsed_lines,
            "status": status,
            "reason": reason,
            "mismatch_examples": " | ".join(mismatch_examples + label_examples),
            "snippet": str(snippet),
        }
    )

with out_csv.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "variant",
            "variant_prefixed",
            "prefetch_src_count",
            "prefetch_objdump_count",
            "parsed_prefetch_lines",
            "pcrel_pass_count",
            "pcrel_fail_count",
            "label_target_pass_count",
            "label_target_fail_count",
            "unparsed_prefetch_lines",
            "status",
            "reason",
            "mismatch_examples",
            "snippet",
        ],
    )
    w.writeheader()
    for r in out_rows:
        w.writerow(r)

if failed:
    raise SystemExit(f"PC-relative validation failed. See {out_csv}")
PY

echo "[phase] prefetch target address checks"
TARGET_ADDR_CSV="${OUT_DIR}/prefetch_target_address_validation.csv"
python3 "${SCRIPT_DIR}/validate_prefetch_target_addresses.py" \
  --repo-root "${PROFILING_DIR}/.." \
  --asm-csv "${ASM_CSV}" \
  --injection-csv "${OUT_DIR}/injection_points_by_depth.csv" \
  --out-csv "${TARGET_ADDR_CSV}"

echo "[phase] adjusted target source-line checks"
python3 "${SCRIPT_DIR}/validate_adjusted_target_srclines.py" \
  --repo-root "${PROFILING_DIR}/.." \
  --asm-csv "${ASM_CSV}" \
  --injection-csv "${OUT_DIR}/injection_points_by_depth.csv" \
  --out-csv "${OUT_DIR}/adjusted_target_srcline_validation.csv" \
  --summary-md "${OUT_DIR}/adjusted_target_srcline_validation.md" \
  --config "${CHIPYARD_CONFIG}"

echo "[phase] run detailed profile + runtime-only"
PROFILE_RUN_LOG="${OUT_DIR}/profile_runtime_runs.log"
: > "${PROFILE_RUN_LOG}"

while IFS=$'\t' read -r variant vp session vdir delay log_path bin_out; do
  wl_name="qsort_${MAX_CYCLES}_${vp}"
  echo "[run] variant=${vp} workload_name=${wl_name}" | tee -a "${PROFILE_RUN_LOG}"

  detailed_summary="${DETAILED_BASE}/${wl_name}/summary.csv"
  runtime_summary="${RUNTIME_BASE}/${wl_name}/$(basename "${bin_out}")/runtime_summary.csv"

  if [[ "${SKIP_EXISTING}" == "1" && -s "${detailed_summary}" ]]; then
    echo "[skip] detailed profile already exists: ${detailed_summary}" | tee -a "${PROFILE_RUN_LOG}"
  else
    /usr/bin/env bash "${PROFILING_DIR}/run_detailed_profile.sh" \
      --workload "${WORKLOAD}" \
      --workload-name "${wl_name}" \
      --sim-binary "${bin_out}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${PROFILE_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --chipyard-config "${CHIPYARD_CONFIG}" \
      --results-base "${DETAILED_BASE}" \
      < /dev/null \
      >> "${PROFILE_RUN_LOG}" 2>&1
  fi

  if [[ "${SKIP_EXISTING}" == "1" && -s "${runtime_summary}" ]]; then
    echo "[skip] runtime-only already exists: ${runtime_summary}" | tee -a "${PROFILE_RUN_LOG}"
  else
    /usr/bin/env bash "${PROFILING_DIR}/run_runtime_only.sh" \
      --workload "${WORKLOAD}" \
      --workload-name "${wl_name}" \
      --sim-binary "${bin_out}" \
      --max-cycles "${MAX_CYCLES}" \
      --iterations "${RUNTIME_ITERATIONS}" \
      --profile-core "${PROFILE_CORE}" \
      --chipyard-config "${CHIPYARD_CONFIG}" \
      --results-base "${RUNTIME_BASE}" \
      < /dev/null \
      >> "${PROFILE_RUN_LOG}" 2>&1
  fi

done < "${rows_tsv}"

echo "[phase] build comparison summaries"
COMPARE_CSV="${OUT_DIR}/comparison_mpki_runtime.csv"
COMPARE_MD="${OUT_DIR}/comparison_mpki_runtime.md"
VALIDATION_MD="${OUT_DIR}/validation_report.md"

python3 - <<'PY' "${rows_tsv}" "${DETAILED_BASE}" "${RUNTIME_BASE}" "${MAX_CYCLES}" "${COMPARE_CSV}" "${COMPARE_MD}" "${VALIDATION_MD}"
import csv
import math
import os
import statistics
import sys

rows_tsv, detailed_base, runtime_base, max_cycles, out_csv, out_md, out_val = sys.argv[1:8]

rows = []
with open(rows_tsv, encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        variant, vp, session, vdir, delay, log_path, bin_out = line.split("\t")
        rows.append((variant, vp, bin_out))

if not rows:
    raise SystemExit("No manifest rows to summarize")

def read_metric_csv(path):
    vals = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vals[r["metric"]] = float(r["mean"])
    return vals

def read_runtime_summary(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = next(csv.DictReader(f))
    return float(r["mean_sec"])

def pct_delta(v, base):
    if base == 0:
        return math.nan
    return (v - base) * 100.0 / base

def fmt(x):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "nan"
    return f"{x:.6f}"

records = []
for variant, vp, bin_out in rows:
    wl = f"qsort_{max_cycles}_{vp}"
    dsum = os.path.join(detailed_base, wl, "summary.csv")
    rsum = os.path.join(runtime_base, wl, os.path.basename(bin_out), "runtime_summary.csv")
    if not os.path.isfile(dsum):
        raise SystemExit(f"Missing detailed summary: {dsum}")
    if not os.path.isfile(rsum):
        raise SystemExit(f"Missing runtime summary: {rsum}")

    d = read_metric_csv(dsum)
    run = read_runtime_summary(rsum)
    records.append({
        "variant": variant,
        "variant_prefixed": vp,
        "binary": bin_out,
        "l1i_mpki": d.get("l1i_mpki", math.nan),
        "l2i_mpki": d.get("l2i_mpki", math.nan),
        "itlb_mpki": d.get("itlb_mpki", math.nan),
        "stlb_mpki": d.get("stlb_mpki", math.nan),
        "perf_elapsed_sec": d.get("elapsed_sec", math.nan),
        "runtime_only_sec": run,
        "instructions": d.get("instructions", math.nan),
    })

base = None
for r in records:
    if r["variant"] == "baseline":
        base = r
        break
if base is None:
    raise SystemExit("Baseline row not found in manifest rows")

for r in records:
    for k in ["l1i_mpki", "l2i_mpki", "itlb_mpki", "stlb_mpki", "perf_elapsed_sec", "runtime_only_sec"]:
        r[f"delta_{k}_pct"] = pct_delta(r[k], base[k])

fieldnames = [
    "variant",
    "variant_prefixed",
    "binary",
    "l1i_mpki",
    "l2i_mpki",
    "itlb_mpki",
    "stlb_mpki",
    "perf_elapsed_sec",
    "runtime_only_sec",
    "instructions",
    "delta_l1i_mpki_pct",
    "delta_l2i_mpki_pct",
    "delta_itlb_mpki_pct",
    "delta_stlb_mpki_pct",
    "delta_perf_elapsed_sec_pct",
    "delta_runtime_only_sec_pct",
]
with open(out_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in records:
        w.writerow(r)

lines = []
lines.append("| Variant | L1I MPKI | L2I MPKI | ITLB MPKI | STLB MPKI | Runtime(no perf,s) | ΔRuntime % |")
lines.append("|---|---:|---:|---:|---:|---:|---:|")
for r in records:
    lines.append(
        "| {vp} | {l1} | {l2} | {itlb} | {stlb} | {rt} | {drt} |".format(
            vp=r["variant_prefixed"],
            l1=fmt(r["l1i_mpki"]),
            l2=fmt(r["l2i_mpki"]),
            itlb=fmt(r["itlb_mpki"]),
            stlb=fmt(r["stlb_mpki"]),
            rt=fmt(r["runtime_only_sec"]),
            drt=fmt(r["delta_runtime_only_sec_pct"]),
        )
    )
with open(out_md, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

# Numeric validation: no NaN/inf/zero for key metrics.
issues = []
for r in records:
    for key in ["l1i_mpki", "l2i_mpki", "itlb_mpki", "stlb_mpki", "perf_elapsed_sec", "runtime_only_sec", "instructions"]:
        v = r[key]
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            issues.append(f"{r['variant_prefixed']}: {key}=nan_or_inf")
        elif v == 0:
            issues.append(f"{r['variant_prefixed']}: {key}=0")

with open(out_val, "w", encoding="utf-8") as f:
    f.write("# Validation\n\n")
    if issues:
        f.write("## Status: FAILED\n")
        for it in issues:
            f.write(f"- {it}\n")
    else:
        f.write("## Status: PASS\n")
        f.write("- All key numeric fields are finite and non-zero across baseline and optimized binaries.\n")

if issues:
    raise SystemExit("Numeric validation failed. See validation_report.md")
PY

echo "[ok] pipeline complete"
echo "[ok] comparison csv: ${COMPARE_CSV}"
echo "[ok] comparison md:  ${COMPARE_MD}"
echo "[ok] validation:     ${VALIDATION_MD}"
echo "[ok] run log:        ${PROFILE_RUN_LOG}"
