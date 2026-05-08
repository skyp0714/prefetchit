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
__attribute__((noinline)) void target(int x) {
  if (x > 0) {
    asm volatile("" ::: "memory"); /* PREFETCHIT_TARGET */
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
  "injections": [
    {
      "target_rank": 1,
      "site_rank": 1,
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

"${CLANG_BIN}" -O0 -g -S -emit-llvm "${TMP_DIR}/smoke.c" -o "${TMP_DIR}/smoke.ll"
"${OPT_BIN}" \
  -load-pass-plugin "${PLUGIN}" \
  -passes=prefetchit-inject \
  -prefetchit-plan="${TMP_DIR}/prefetchit.plan.json" \
  "${TMP_DIR}/smoke.ll" -S -o "${TMP_DIR}/smoke.prefetch.ll" \
  2> "${TMP_DIR}/opt.log"

grep -q 'prefetchit0' "${TMP_DIR}/smoke.prefetch.ll"
grep -q 'blockaddress(@target' "${TMP_DIR}/smoke.prefetch.ll"
grep -q 'injected=1' "${TMP_DIR}/opt.log"

"${LLC_BIN}" -mattr=+prefetchi "${TMP_DIR}/smoke.prefetch.ll" -o "${TMP_DIR}/smoke.s"
grep -Eq 'prefetchit0[[:space:]]+\.L[^[:space:]]*\(%rip\)' "${TMP_DIR}/smoke.s"

echo "[ok] smoke test passed"
