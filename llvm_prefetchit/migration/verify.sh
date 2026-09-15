#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${PREFETCHIT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
CHECK_HOST=1
failures=0

fail() { echo "[fail] $*" >&2; failures=$((failures + 1)); }
ok() { echo "[ok] $*"; }

usage() {
  cat <<'EOF'
Usage: verify.sh [--root PATH] [--source-only]

  --root PATH     PrefetchIT root (a positional PATH is also accepted)
  --source-only   Verify Git state, manifests, patches, and script syntax only
  -h, --help      Show this help

Without --source-only, the verifier also requires the analysis/build tools and
a perf binary that can run on the current kernel.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$(readlink -m "${2:?missing --root value}")"; shift 2 ;;
    --source-only) CHECK_HOST=0; shift ;;
    -h|--help) usage; exit 0 ;;
    --*) echo "[err] unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) ROOT="$(readlink -m "$1")"; shift ;;
  esac
done

for file in repos.lock.tsv benchmarks.lock.tsv tools.lock.tsv; do
  [[ -s "${SCRIPT_DIR}/${file}" ]] || fail "missing ${file}"
done

while IFS=$'\t' read -r rel url branch revision role; do
  [[ -z "${rel}" || "${rel}" == \#* ]] && continue
  dest="${ROOT}/${rel}"
  if ! git -C "${dest}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fail "missing component ${rel}"
    continue
  fi
  actual="$(git -C "${dest}" rev-parse HEAD)"
  if [[ "${revision}" != "SELF" ]]; then
    [[ "${actual}" == "${revision}" ]] || fail "${rel}: expected ${revision}, got ${actual}"
  fi
  [[ -z "$(git -C "${dest}" status --porcelain)" ]] || fail "${rel}: dirty worktree"
  ok "${rel} @ ${actual}"
done < "${SCRIPT_DIR}/repos.lock.tsv"

for patch_file in "${SCRIPT_DIR}"/patches/*.patch; do
  [[ -s "${patch_file}" ]] || fail "empty patch $(basename "${patch_file}")"
done

for evidence_file in \
  evidence/verilator/summary_20260901.csv \
  evidence/verilator/crosspayload_fixed38_runs.csv \
  evidence/verilator/qsort_fixed38_runs.csv \
  evidence/verilator/topvariant_fixed38_runs.csv \
  evidence/django/rep1_runs.csv \
  evidence/django/rep2_runs.csv \
  evidence/django/rep3_runs.csv \
  evidence/feedsim/runs.csv; do
  [[ -s "${SCRIPT_DIR}/${evidence_file}" ]] || fail "missing canonical evidence ${evidence_file}"
done

if ! awk -F '\t' 'NF != 14 { exit 1 }' "${SCRIPT_DIR}/core_results.tsv"; then
  fail "core_results.tsv does not have 14 columns on every row"
fi

for script in "${SCRIPT_DIR}"/*.sh; do
  bash -n "${script}" || fail "shell syntax: ${script}"
done

for repo in llvm_prefetchit profiling icache_microbenchmark static_cond_prefetch static_return_prefetch flat_codegen jit_prefetch; do
  dest="${ROOT}/${repo}"
  [[ -d "${dest}/.git" ]] || continue
  if git -C "${dest}" grep -En "echo +['\"][^'\"]+['\"] +[|] +sudo +-S" HEAD -- >/dev/null 2>&1; then
    fail "${repo}: tracked plaintext value piped to sudo -S"
  fi
  large="$(git -C "${dest}" ls-tree -rl HEAD | awk '$4 > 95000000 {print $4 " " $5; exit}')"
  [[ -z "${large}" ]] || fail "${repo}: GitHub-size tracked blob ${large}"
done

for cmd in git python3; do
  command -v "${cmd}" >/dev/null 2>&1 || fail "missing command ${cmd}"
done

if [[ "${CHECK_HOST}" == 1 ]]; then
  for cmd in cmake ninja jq rg clang-19 opt-19 llvm-config-19; do
    command -v "${cmd}" >/dev/null 2>&1 || fail "missing command ${cmd}"
  done

  if ! perf --version >/dev/null 2>&1; then
    fail "perf is missing or does not match kernel $(uname -r)"
  fi
fi

if ((failures)); then
  echo "[done] verification failed: ${failures} issue(s)" >&2
  exit 1
fi
echo "[done] migration verification passed"
