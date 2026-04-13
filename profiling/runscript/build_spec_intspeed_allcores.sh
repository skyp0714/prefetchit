#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SPEC_ROOT="${REPO_ROOT}/benchmarks/cpu2017"
LOG_DIR="${REPO_ROOT}/profiling/results/benchmark_runs/logs"
mkdir -p "${LOG_DIR}"

if [[ ! -d "${SPEC_ROOT}" ]]; then
  echo "[err] cpu2017 root not found: ${SPEC_ROOT}" >&2
  exit 1
fi

cd "${SPEC_ROOT}"
source shrc

BUILD_NCPUS="${BUILD_NCPUS:-$(nproc)}"
SPEC_CONFIG="${SPEC_CONFIG:-gnr3-profile}"

runcpu \
  --config="${SPEC_CONFIG}" \
  --define build_ncpus="${BUILD_NCPUS}" \
  --action=build \
  --tune=base \
  --noreportable \
  intspeed | tee "${LOG_DIR}/spec_intspeed_build.log"
