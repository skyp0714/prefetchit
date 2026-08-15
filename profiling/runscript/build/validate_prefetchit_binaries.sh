#!/usr/bin/env bash
set -euo pipefail

MANIFEST=""
OUT_DIR=""
POLL_SEC="300"
LLVM_OBJDUMP="llvm-objdump-19"
PATCH_SUMMARY=""

usage() {
  cat <<'USAGE'
Usage: validate_prefetchit_binaries.sh --manifest <build_manifest.csv> [options]

Options:
  --manifest <path>          Build manifest CSV (required)
  --out-dir <path>           Validation output dir (default: <manifest_dir>/validation_<timestamp>)
  --poll-sec <N>             Poll interval while waiting binaries (default: 300)
  --llvm-objdump <bin/path>  llvm-objdump binary (default: llvm-objdump-19)
  --patch-summary <path>     Optional variant_patch_summary.csv for expected instruction counts
  -h, --help                 Show help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      MANIFEST="${2:-}"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --poll-sec)
      POLL_SEC="${2:-}"
      shift 2
      ;;
    --llvm-objdump)
      LLVM_OBJDUMP="${2:-}"
      shift 2
      ;;
    --patch-summary)
      PATCH_SUMMARY="${2:-}"
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

if [[ -z "${MANIFEST}" || ! -f "${MANIFEST}" ]]; then
  echo "[err] --manifest is required and must exist" >&2
  exit 1
fi
if ! [[ "${POLL_SEC}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --poll-sec must be positive integer" >&2
  exit 1
fi
if ! command -v "${LLVM_OBJDUMP}" >/dev/null 2>&1; then
  echo "[err] llvm-objdump not found: ${LLVM_OBJDUMP}" >&2
  exit 1
fi

if [[ -z "${OUT_DIR}" ]]; then
  ts="$(date +%Y%m%d_%H%M%S)"
  OUT_DIR="$(cd "$(dirname "${MANIFEST}")" && pwd)/validation_${ts}"
fi
mkdir -p "${OUT_DIR}"

rows_tsv="${OUT_DIR}/manifest_rows.tsv"
tail -n +2 "${MANIFEST}" | awk -F, 'NF>=7 {print $1"\t"$2"\t"$3"\t"$4"\t"$5"\t"$6"\t"$7}' > "${rows_tsv}"
if [[ ! -s "${rows_tsv}" ]]; then
  echo "[err] no rows parsed from manifest" >&2
  exit 1
fi

echo "[inf] manifest=${MANIFEST}"
echo "[inf] out_dir=${OUT_DIR}"

echo "[phase] waiting for binaries"
wait_log="${OUT_DIR}/wait.log"
: > "${wait_log}"
while IFS=$'\t' read -r variant vp session vdir delay log_path bin_out; do
  echo "[wait] ${vp}"
  while true; do
    now="$(date '+%F %T')"
    if [[ -s "${bin_out}" ]]; then
      echo "${now} [ok] binary ready ${vp}: ${bin_out}" | tee -a "${wait_log}"
      break
    fi
    if [[ -f "${log_path}" ]] && rg -n "^make(\[[0-9]+\])?: \*\*\*" "${log_path}" >/dev/null 2>&1; then
      echo "${now} [err] build failed for ${vp}: ${log_path}" | tee -a "${wait_log}" >&2
      exit 1
    fi
    echo "${now} [inf] waiting ${vp}" | tee -a "${wait_log}"
    sleep "${POLL_SEC}"
  done
done < "${rows_tsv}"

echo "[phase] binary + pcrel validation"
DEBUG_CSV="${OUT_DIR}/binary_debug_check.csv"
PCREL_CSV="${OUT_DIR}/prefetch_pcrel_validation.csv"
echo "variant,variant_prefixed,binary,symbol_text_count,text_bytes,text_mib,nm_head_file" > "${DEBUG_CSV}"

python3 - <<'PY' "${rows_tsv}" "${DEBUG_CSV}" "${PCREL_CSV}" "${OUT_DIR}" "${LLVM_OBJDUMP}" "${PATCH_SUMMARY}"
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

rows_tsv, debug_csv, pcrel_csv, out_dir, llvm_objdump, patch_summary = sys.argv[1:7]
out_dir = Path(out_dir)

line_re = re.compile(
    r"^\s*(?:\d+:)?\s*([0-9a-fA-F]+):\s+[0-9a-fA-F ]+\s+prefetchit[01]\s+([+-]?(?:0x[0-9a-fA-F]+|\d+))\(%rip\)\s+#\s+0x([0-9a-fA-F]+)(?:\s+<([^>]+)>)?"
)
instr_re = re.compile(r"^\s*(?:\d+:)?\s*[0-9a-fA-F]+:\s+.*\bprefetchit[01]\b")

expected_inst = {}
if patch_summary and Path(patch_summary).is_file():
    with open(patch_summary, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            expected_inst[r.get("variant_short", "")] = int(r.get("inserted_prefetch_instructions", "0") or 0)

rows = []
with open(rows_tsv, encoding="utf-8") as f:
    for ln in f:
        ln = ln.strip()
        if not ln:
            continue
        rows.append(ln.split("\t"))

pcrel_rows = []
failed = False

with open(debug_csv, "a", newline="", encoding="utf-8") as df:
    dw = csv.writer(df)

    for row in rows:
        variant, vp, session, vdir, delay, log_path, bin_out = row
        bin_path = Path(bin_out)

        nm_head_file = out_dir / f"nm_{vp}.head20.txt"
        nm_head = subprocess.run(["nm", "-C", str(bin_path)], text=True, capture_output=True, check=False).stdout.splitlines()
        nm_head_file.write_text("\n".join(nm_head[:20]) + ("\n" if nm_head else ""), encoding="utf-8")

        nm_defined = subprocess.run(["nm", "-C", "--defined-only", str(bin_path)], text=True, capture_output=True, check=True).stdout.splitlines()
        sym_count = 0
        for ln in nm_defined:
            parts = ln.split()
            if len(parts) >= 2 and re.match(r"[Tt]", parts[1]):
                sym_count += 1

        text_hex = ""
        obj_hdr = subprocess.run(["objdump", "-h", str(bin_path)], text=True, capture_output=True, check=True).stdout.splitlines()
        for ln in obj_hdr:
            parts = ln.split()
            if len(parts) >= 3 and parts[1] == ".text":
                text_hex = parts[2]
                break
        text_bytes = int(text_hex, 16) if text_hex else 0
        text_mib = text_bytes / 1048576.0

        dw.writerow([variant, vp, str(bin_path), sym_count, text_bytes, f"{text_mib:.3f}", str(nm_head_file)])

        dis = subprocess.run([llvm_objdump, "-d", str(bin_path)], text=True, capture_output=True, check=True).stdout.splitlines()
        snippet = out_dir / f"disasm_{vp}_prefetch.txt"
        # The binary path itself may contain "prefetchit"; count only disassembly
        # instruction lines, not llvm-objdump's file-format header.
        pref_lines = [ln for ln in dis if instr_re.match(ln)]
        snippet.write_text("\n".join(pref_lines) + ("\n" if pref_lines else ""), encoding="utf-8")

        parsed = 0
        pass_cnt = 0
        fail_cnt = 0
        unparsed = 0
        mismatch = []
        for ln in pref_lines:
            m = line_re.match(ln)
            if not m:
                unparsed += 1
                continue
            parsed += 1
            insn_addr = int(m.group(1), 16)
            disp = int(m.group(2), 0)
            tgt_addr = int(m.group(3), 16)
            calc = (insn_addr + 7 + disp) & ((1 << 64) - 1)
            if calc == tgt_addr:
                pass_cnt += 1
            else:
                fail_cnt += 1
                if len(mismatch) < 5:
                    mismatch.append(f"insn=0x{insn_addr:x} disp={disp} calc=0x{calc:x} target=0x{tgt_addr:x}")

        exp = expected_inst.get(variant, None)
        # variant column is short name from manifest row.
        status = "ok"
        reason = ""
        if variant == "baseline":
            if len(pref_lines) != 0:
                status = "fail"
                reason = "baseline_has_prefetchit"
        else:
            if len(pref_lines) == 0:
                status = "fail"
                reason = "missing_prefetchit_in_binary"
            elif parsed == 0:
                status = "fail"
                reason = "no_parsed_prefetch_lines"
            elif fail_cnt > 0:
                status = "fail"
                reason = "pcrel_mismatch"
            elif exp is not None and len(pref_lines) < exp:
                status = "warn"
                reason = f"prefetch_count_lt_expected({len(pref_lines)}<{exp})"

        if status == "fail":
            failed = True

        pcrel_rows.append(
            {
                "variant": variant,
                "variant_prefixed": vp,
                "binary": str(bin_path),
                "prefetch_count": len(pref_lines),
                "parsed_prefetch_lines": parsed,
                "pcrel_pass_count": pass_cnt,
                "pcrel_fail_count": fail_cnt,
                "unparsed_prefetch_lines": unparsed,
                "expected_min_prefetch_count": "" if exp is None else exp,
                "status": status,
                "reason": reason,
                "mismatch_examples": " | ".join(mismatch),
                "disasm_snippet": str(snippet),
            }
        )

with open(pcrel_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(
        f,
        fieldnames=[
            "variant",
            "variant_prefixed",
            "binary",
            "prefetch_count",
            "parsed_prefetch_lines",
            "pcrel_pass_count",
            "pcrel_fail_count",
            "unparsed_prefetch_lines",
            "expected_min_prefetch_count",
            "status",
            "reason",
            "mismatch_examples",
            "disasm_snippet",
        ],
    )
    w.writeheader()
    for r in pcrel_rows:
        w.writerow(r)

if failed:
    raise SystemExit(f"PC-relative validation failed. See {pcrel_csv}")
PY

echo "[ok] debug report: ${DEBUG_CSV}"
echo "[ok] pcrel report: ${PCREL_CSV}"
