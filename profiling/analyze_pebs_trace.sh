#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILING_DIR="${SCRIPT_DIR}"
PYTHON_BIN="${PROFILING_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

PERF_BIN="${PERF_BIN:-perf}"
DATA_FILE="${DATA_FILE:-}"
OUT_DIR="${OUT_DIR:-}"
EVENT_LABEL="${EVENT_LABEL:-}"
SIM_BINARY="${SIM_BINARY:-}"
ADDR2LINE_BIN="${ADDR2LINE_BIN:-}"

usage() {
  cat <<'EOF'
Usage: ./analyze_pebs_trace.sh --data <perf.data> [options]

Options:
  --data <path>          Input perf data file (required)
  --out-dir <path>       Output directory (default: dirname(data))
  --event-label <name>   Label for summary/plots
  --binary <path>        Target simulator binary for srcline resolution (optional)
  --addr2line-bin <path> addr2line binary path override (optional)
  --perf-bin <path>      Perf binary path (default: perf)
  -h, --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data)
      DATA_FILE="${2:-}"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --event-label)
      EVENT_LABEL="${2:-}"
      shift 2
      ;;
    --binary)
      SIM_BINARY="${2:-}"
      shift 2
      ;;
    --addr2line-bin)
      ADDR2LINE_BIN="${2:-}"
      shift 2
      ;;
    --perf-bin)
      PERF_BIN="${2:-}"
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

if [[ -z "${DATA_FILE}" ]]; then
  echo "[err] --data is required" >&2
  exit 1
fi
if [[ ! -f "${DATA_FILE}" ]]; then
  echo "[err] missing data file: ${DATA_FILE}" >&2
  exit 1
fi
if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="$(cd "$(dirname "${DATA_FILE}")" && pwd)"
fi
mkdir -p "${OUT_DIR}"

LBR_RAW_TXT="${OUT_DIR}/lbr_raw_dump.txt"
LBR_SYM_TXT="${OUT_DIR}/lbr_symbolic_dump.txt"
BRANCH_TYPE_CSV="${OUT_DIR}/branch_type_distribution.csv"
TARGET_BRANCH_CSV="${OUT_DIR}/target_branch_counts.csv"
SUMMARY_MD="${OUT_DIR}/trace_summary.md"
DETAILED_MD="${OUT_DIR}/detailed_trace_report.md"
HIERARCHICAL_MD="${OUT_DIR}/hierarchical_miss_report.md"
HIERARCHICAL_TXT="${OUT_DIR}/hierarchical_miss_report.txt"

# Clean stale outputs from older latency-enabled flow.
rm -f "${OUT_DIR}/miss_latencies.txt" "${OUT_DIR}/latency_histogram.csv" "${OUT_DIR}/latency_histogram.png"
rm -f "${HIERARCHICAL_MD}" "${HIERARCHICAL_TXT}"

echo "[run] perf script (LBR raw)"
if ! "${PERF_BIN}" script -i "${DATA_FILE}" -F ip,sym,brstack,weight > "${LBR_RAW_TXT}" 2>"${OUT_DIR}/perf_script_raw.err"; then
  if grep -qi "WEIGHT attribute" "${OUT_DIR}/perf_script_raw.err"; then
    echo "[inf] samples do not carry weight; retrying raw LBR dump without weight"
    "${PERF_BIN}" script -i "${DATA_FILE}" -F ip,sym,brstack > "${LBR_RAW_TXT}"
  else
    cat "${OUT_DIR}/perf_script_raw.err" >&2
    exit 1
  fi
fi

echo "[run] perf script (LBR symbolic)"
if ! "${PERF_BIN}" script -i "${DATA_FILE}" -F ip,sym,brstacksym,weight > "${LBR_SYM_TXT}" 2>"${OUT_DIR}/perf_script_sym.err"; then
  if grep -qi "WEIGHT attribute" "${OUT_DIR}/perf_script_sym.err"; then
    echo "[inf] samples do not carry weight; retrying symbolic LBR dump without weight"
    "${PERF_BIN}" script -i "${DATA_FILE}" -F ip,sym,brstacksym > "${LBR_SYM_TXT}"
  else
    cat "${OUT_DIR}/perf_script_sym.err" >&2
    exit 1
  fi
fi

echo "[run] build summary csv"
build_cmd=(
  "${PYTHON_BIN}" "${PROFILING_DIR}/runscript/build/build_pebs_trace_outputs.py"
  --lbr-raw "${LBR_RAW_TXT}"
  --lbr-sym "${LBR_SYM_TXT}"
  --out-branch-csv "${BRANCH_TYPE_CSV}"
  --out-target-branch-csv "${TARGET_BRANCH_CSV}"
  --out-hierarchical-report "${HIERARCHICAL_MD}"
  --out-detailed-md "${DETAILED_MD}"
  --out-summary-md "${SUMMARY_MD}"
  --event-label "${EVENT_LABEL}"
)
if [[ -n "${SIM_BINARY}" ]]; then
  build_cmd+=(--sim-binary "${SIM_BINARY}")
fi
if [[ -n "${ADDR2LINE_BIN}" ]]; then
  build_cmd+=(--addr2line-bin "${ADDR2LINE_BIN}")
fi
"${build_cmd[@]}"
cp -f "${HIERARCHICAL_MD}" "${HIERARCHICAL_TXT}"

echo
echo "[ok] saved ${LBR_RAW_TXT}"
echo "[ok] saved ${LBR_SYM_TXT}"
echo "[ok] saved ${BRANCH_TYPE_CSV}"
echo "[ok] saved ${TARGET_BRANCH_CSV}"
echo "[ok] saved ${HIERARCHICAL_MD}"
echo "[ok] saved ${HIERARCHICAL_TXT}"
echo "[ok] saved ${DETAILED_MD}"
echo "[ok] saved ${SUMMARY_MD}"
