#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BUILD_DIR="${1:-${ROOT_DIR}/build}"

CLANG_BIN="${CLANG_BIN:-clang-19}"
OPT_BIN="${OPT_BIN:-opt-19}"
LLC_BIN="${LLC_BIN:-llc-19}"
PLUGIN="${PREFETCHIT_PLUGIN:-${BUILD_DIR}/PrefetchITPass.so}"

if [[ ! -f "${PLUGIN}" ]]; then
  echo "[err] plugin not found: ${PLUGIN}" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

cat > "${TMP_DIR}/smoke.c" <<'SRC'
volatile int sink;

__attribute__((noinline)) void target(int x) {
  if (x > 0) {
    sink += x;
    asm volatile("" ::: "memory"); /* PREFETCHIT_TARGET */
    sink += 7;
  }
}

__attribute__((noinline)) void caller(int x) {
  if (x & 1) { /* PREFETCHIT_SITE */
    target(x);
  }
}
SRC

target_line="$(grep -n 'PREFETCHIT_TARGET' "${TMP_DIR}/smoke.c" | cut -d: -f1)"
site_line="$(grep -n 'PREFETCHIT_SITE' "${TMP_DIR}/smoke.c" | cut -d: -f1)"

cat > "${TMP_DIR}/prefetchit.plan.json" <<JSON
{
  "schema": "prefetchit.plan.v1",
  "prefetch": {
    "mnemonic": "prefetcht1",
    "operand": "pc-relative-blockaddress",
    "byte_offsets": [0, 64, 128]
  },
  "injections": [
    {
      "target_rank": 1,
      "site_rank": 1,
      "prefetch_mnemonic": "prefetcht1",
      "samples": 10,
      "new_covered_samples": 10,
      "cumulative_coverage_pct": 100.0,
      "target": {
        "mangled": "target",
        "demangled": "target",
        "function": "target",
        "file": "${TMP_DIR}/smoke.c",
        "line": ${target_line},
        "addr": "0x0"
      },
      "site": {
        "mangled": "caller",
        "demangled": "caller",
        "function": "caller",
        "file": "${TMP_DIR}/smoke.c",
        "line": ${site_line},
        "addr": "0x0",
        "branch_type": "COND",
        "lbr_depth": 1
      }
    }
  ]
}
JSON

cat > "${TMP_DIR}/prefetchit.symbol.plan.json" <<JSON
{
  "schema": "prefetchit.plan.v1",
  "prefetch": {
    "mnemonic": "prefetcht1",
    "operand": "pc-relative-symbol-offset",
    "byte_offsets": [0, 64, 128],
    "lead_instructions": 2
  },
  "injections": [
    {
      "target_rank": 1,
      "site_rank": 1,
      "prefetch_mnemonic": "prefetcht1",
      "samples": 10,
      "new_covered_samples": 10,
      "cumulative_coverage_pct": 100.0,
      "target": {
        "mangled": "target",
        "demangled": "target",
        "function": "target",
        "file": "${TMP_DIR}/smoke.c",
        "line": ${target_line},
        "addr": "0x0",
        "symbol_offset": "0x10"
      },
      "site": {
        "mangled": "caller",
        "demangled": "caller",
        "function": "caller",
        "file": "${TMP_DIR}/smoke.c",
        "line": ${site_line},
        "addr": "0x0",
        "branch_type": "COND",
        "lbr_depth": 1
      }
    }
  ]
}
JSON

"${CLANG_BIN}" -O0 -g -S -emit-llvm "${TMP_DIR}/smoke.c" -o "${TMP_DIR}/smoke.ll"

run_case() {
  local mnemonic="$1"
  local override_arg=()
  if [[ "$mnemonic" != "prefetcht1" ]]; then
    override_arg=(-prefetchit-mnemonic="${mnemonic}")
  fi

  "${OPT_BIN}" \
    -load-pass-plugin "${PLUGIN}" \
    -passes=prefetchit-inject \
    -prefetchit-plan="${TMP_DIR}/prefetchit.plan.json" \
    "${override_arg[@]}" \
    "${TMP_DIR}/smoke.ll" -S -o "${TMP_DIR}/smoke.${mnemonic}.ll" \
    2> "${TMP_DIR}/opt.${mnemonic}.log"

  grep -q "${mnemonic}" "${TMP_DIR}/smoke.${mnemonic}.ll"
  grep -q 'blockaddress(@target' "${TMP_DIR}/smoke.${mnemonic}.ll"
  grep -q 'prefetchit.target' "${TMP_DIR}/smoke.${mnemonic}.ll"
  grep -q 'injected=3' "${TMP_DIR}/opt.${mnemonic}.log"
  grep -q 'target_block_split=1' "${TMP_DIR}/opt.${mnemonic}.log"

  "${LLC_BIN}" "${TMP_DIR}/smoke.${mnemonic}.ll" -o "${TMP_DIR}/smoke.${mnemonic}.s"
  grep -Eq "${mnemonic}[[:space:]]+\\.L[^[:space:]]*\\(%rip\\)" "${TMP_DIR}/smoke.${mnemonic}.s"
  grep -Eq "${mnemonic}[[:space:]]+\\.L[^[:space:]]*\\+64\\(%rip\\)" "${TMP_DIR}/smoke.${mnemonic}.s"
  grep -Eq "${mnemonic}[[:space:]]+\\.L[^[:space:]]*\\+128\\(%rip\\)" "${TMP_DIR}/smoke.${mnemonic}.s"
}

run_case prefetcht1
run_case prefetcht2

"${OPT_BIN}" \
  -load-pass-plugin "${PLUGIN}" \
  -passes=prefetchit-inject \
  -prefetchit-plan="${TMP_DIR}/prefetchit.symbol.plan.json" \
  "${TMP_DIR}/smoke.ll" -S -o "${TMP_DIR}/smoke.symbol.ll" \
  2> "${TMP_DIR}/opt.symbol.log"

grep -q 'prefetcht1 target+0x10(%rip)' "${TMP_DIR}/smoke.symbol.ll"
grep -q 'prefetcht1 target+0x50(%rip)' "${TMP_DIR}/smoke.symbol.ll"
grep -q 'prefetcht1 target+0x90(%rip)' "${TMP_DIR}/smoke.symbol.ll"
grep -q 'symbol_offset_target=3' "${TMP_DIR}/opt.symbol.log"
grep -q 'lead_adjusted_sites=1' "${TMP_DIR}/opt.symbol.log"
"${LLC_BIN}" "${TMP_DIR}/smoke.symbol.ll" -o "${TMP_DIR}/smoke.symbol.s"
grep -Fq 'prefetcht1	target+16(%rip)' "${TMP_DIR}/smoke.symbol.s"
grep -Fq 'prefetcht1	target+80(%rip)' "${TMP_DIR}/smoke.symbol.s"
grep -Fq 'prefetcht1	target+144(%rip)' "${TMP_DIR}/smoke.symbol.s"

python3 - "${TMP_DIR}/prefetchit.symbol.plan.json" "${TMP_DIR}/prefetchit.local.plan.json" <<'PY'
import json
import pathlib
import sys

plan = json.loads(pathlib.Path(sys.argv[1]).read_text())
plan["injections"][0]["target"]["symbol_type"] = "t"
pathlib.Path(sys.argv[2]).write_text(json.dumps(plan))
PY
"${OPT_BIN}" \
  -load-pass-plugin "${PLUGIN}" \
  -passes=prefetchit-inject \
  -prefetchit-plan="${TMP_DIR}/prefetchit.local.plan.json" \
  "${TMP_DIR}/smoke.ll" -S -o "${TMP_DIR}/smoke.local.ll" \
  2> "${TMP_DIR}/opt.local.log"
grep -q 'blockaddress(@target' "${TMP_DIR}/smoke.local.ll"
grep -q 'blockaddress_target=3' "${TMP_DIR}/opt.local.log"
grep -q 'symbol_offset_target=0' "${TMP_DIR}/opt.local.log"

python3 "${ROOT_DIR}/tests/test_trace_to_plan.py"

echo "[ok] smoke test passed"
