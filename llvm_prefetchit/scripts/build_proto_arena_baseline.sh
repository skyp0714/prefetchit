#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: $0 OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit"
REPO="${FLEETBENCH_REPO:-${ROOT}/benchmarks/fleetbench}"
OUT="$(readlink -m "$1")"
BAZEL="${BAZEL:-${ROOT}/llvm_prefetchit/work/pgo_goal_20260713/tools/bazelisk}"
PLATFORM_SUFFIX="${PLATFORM_SUFFIX:-clang_proto_clean_lbr2}"

[[ -x "${BAZEL}" && -f "${REPO}/.bazelversion" ]]
mkdir -p "${OUT}"
(
  cd "${REPO}"
  env -u PREFETCHIT_PLAN PATH="/usr/lib/llvm-19/bin:${PATH}" \
    USE_BAZEL_VERSION=8.0.0 "${BAZEL}" build \
      --config=clang --config=opt --config=haswell --strip=never \
      --copt=-gline-tables-only --linkopt=-Wl,--build-id=sha1 \
      "--platform_suffix=${PLATFORM_SUFFIX}" \
      //fleetbench/proto:proto_benchmark
) >"${OUT}/build.log" 2>&1

if rg -q 'prefetchit-inject|fpass-plugin' "${OUT}/build.log"; then
  echo "clean baseline unexpectedly loaded PrefetchIT" >&2
  exit 1
fi
source_binary="$(readlink -f "${REPO}/bazel-bin/fleetbench/proto/proto_benchmark")"
binary="${OUT}/proto_benchmark.clean"
cp -p "${source_binary}" "${binary}"
llvm-readelf-19 -SW "${binary}" | rg -q '\.debug_line'
{
  printf 'source_binary=%s\n' "${source_binary}"
  printf 'output_binary=%s\n' "${binary}"
  printf 'fleetbench_revision=%s\n' "$(git -C "${REPO}" rev-parse HEAD)"
  printf 'platform_suffix=%s\n' "${PLATFORM_SUFFIX}"
  sha256sum "${binary}"
} >"${OUT}/baseline.conf"
printf '%s\n' "${binary}"
