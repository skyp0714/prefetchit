#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

BINARY="${BINARY:-benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig}"
TRACE_ROOT="${TRACE_ROOT:-llvm_prefetchit/results/trace_aggregation/foreground_agg_l2_20260603_145906/traces}"
OUT="${OUT:-static_prefetch/results/cond_static_sweep_$(date +%Y%m%d_%H%M%S)}"

mkdir -p "${OUT}"

static_prefetch/tools/cond/sweep_static_cond_algorithms.py \
  --binary "${BINARY}" \
  --trace-dir "${TRACE_ROOT}/baseline_qsort_538240_trace01/l2_miss" \
  --trace-dir "${TRACE_ROOT}/baseline_qsort_538240_trace02/l2_miss" \
  --trace-dir "${TRACE_ROOT}/baseline_qsort_538240_trace03/l2_miss" \
  --out-dir "${OUT}" \
  --target-k 5000

static_prefetch/tools/cond/hybridize_cond_candidates.py \
  --prefix-csv "${OUT}/candidates/static_cond_tail-sparse.csv" \
  --tail-csv "${OUT}/candidates/static_cond_span.csv" \
  --prefix-count 10000 \
  --out-csv "${OUT}/candidates/static_cond_hybrid_tail10k_span.csv"

static_prefetch/tools/cond/evaluate_static_cond_targets.py \
  --binary "${BINARY}" \
  --candidates "${OUT}/candidates/static_cond_hybrid_tail10k_span.csv" \
  --trace-dir "${TRACE_ROOT}/baseline_qsort_538240_trace01/l2_miss" \
  --trace-dir "${TRACE_ROOT}/baseline_qsort_538240_trace02/l2_miss" \
  --trace-dir "${TRACE_ROOT}/baseline_qsort_538240_trace03/l2_miss" \
  --out-dir "${OUT}/eval/hybrid_tail10k_span" \
  --ks 100,500,1000,2500,5000,10000,25000,50000,100000,150000

echo "${OUT}"
