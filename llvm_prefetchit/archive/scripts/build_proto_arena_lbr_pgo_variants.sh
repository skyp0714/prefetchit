#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 PLAN_VARIANTS_DIR OUT_DIR" >&2
  exit 2
fi

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PASS_ROOT="${ROOT}/llvm_prefetchit"
REPO="${FLEETBENCH_REPO:-${ROOT}/benchmarks/fleetbench}"
PLANS="$(readlink -f "$1")"
OUT="$(readlink -m "$2")"
BAZEL="${BAZEL:-${PASS_ROOT}/work/pgo_goal_20260713/tools/bazelisk}"
VARIANTS="${BUILD_VARIANTS:-cov25_d1_32_b4_o0 cov25_d1_32_b4_o064}"
PLATFORM_SUFFIX="${PLATFORM_SUFFIX:-clang_proto_pgo_live}"
SOURCE_FILTER="${SOURCE_FILTER:-.*(fleetbench/proto|protobuf|tcmalloc|llvm-project|abseil-cpp|libpfm|benchmark).*}"
JOBS="${JOBS:-12}"
VALIDATOR="${PASS_ROOT}/tools/validate_prefetch_asm.py"
BASELINE_BINARY="${BASELINE_BINARY:-${PASS_ROOT}/work/pgo_goal_20260713/bins/proto_arena/proto_benchmark.clean_lbr2}"

[[ -x "${BAZEL}" && -f "${VALIDATOR}" && -x "${BASELINE_BINARY}" ]]
mkdir -p "${OUT}/bins" "${OUT}/plugins" "${OUT}/validation"
baseline_prefetches="$(llvm-objdump-19 -d "${BASELINE_BINARY}" | rg -c '\bprefetcht1\b' || true)"
baseline_prefetches="${baseline_prefetches:-0}"
printf 'label,status,planned_injections,planned_prefetches,logged_injections,baseline_prefetches,linked_prefetches,linked_delta,validator_rc,sha256,binary,plugin\n' \
  >"${OUT}/build_summary.csv"

build_embedded_plugin() {
  local label="$1" plan="$2" build_dir plugin
  build_dir="${OUT}/plugins/${label}/build"
  plugin="${OUT}/plugins/${label}/PrefetchITPass.so"
  mkdir -p "${build_dir}"
  cmake -S "${PASS_ROOT}" -B "${build_dir}" \
    -DLLVM_DIR=/usr/lib/llvm-19/lib/cmake/llvm \
    -DCMAKE_BUILD_TYPE=Release \
    "-DPREFETCHIT_DEFAULT_PLAN=${plan}" \
    >"${OUT}/plugins/${label}/configure.log" 2>&1
  cmake --build "${build_dir}" -j"${JOBS}" \
    >"${OUT}/plugins/${label}/build.log" 2>&1
  cp -p "${build_dir}/PrefetchITPass.so" "${plugin}"
  printf '%s\n' "${plugin}"
}

for label in ${VARIANTS}; do
  plan="${PLANS}/${label}/prefetchit.plan.json"
  [[ -s "${plan}" ]] || { echo "missing plan: ${plan}" >&2; exit 2; }
  plan="$(readlink -f "${plan}")"
  tag="$(sha256sum "${plan}" | awk '{print toupper(substr($1, 1, 16))}')"
  plugin="$(build_embedded_plugin "${label}" "${plan}")"
  log="${OUT}/build_${label}.log"
  per_file="${SOURCE_FILTER}@-fpass-plugin=${plugin},-DPREFETCHIT_PLAN_TAG_${tag}=1"

  (
    cd "${REPO}"
    env -u PREFETCHIT_PLAN PATH="/usr/lib/llvm-19/bin:${PATH}" \
      USE_BAZEL_VERSION=8.0.0 "${BAZEL}" build \
        --config=clang --config=opt --config=haswell --strip=never \
        --copt=-gline-tables-only --linkopt=-Wl,--build-id=sha1 \
        "--platform_suffix=${PLATFORM_SUFFIX}" \
        "--per_file_copt=${per_file}" \
        //fleetbench/proto:proto_benchmark
  ) >"${log}" 2>&1

  source_binary="$(readlink -f "${REPO}/bazel-bin/fleetbench/proto/proto_benchmark")"
  binary="${OUT}/bins/proto_benchmark.${label}"
  rm -f "${binary}"
  cp -p "${source_binary}" "${binary}"
  llvm-readelf-19 -SW "${binary}" | rg -q '\.debug_line'
  set +e
  python3 "${VALIDATOR}" --binary "${binary}" --plan "${plan}" \
    --build-log "${log}" --out-dir "${OUT}/validation/${label}" \
    >"${OUT}/validation/${label}.log" 2>&1
  validator_rc="$?"
  set -e

  planned_injections="$(jq -r '.stats.selected_injections' "${plan}")"
  planned_prefetches="$(jq -r '.stats.planned_prefetches' "${plan}")"
  logged_injections="$(python3 - "${log}" <<'PY'
import re, sys
text = open(sys.argv[1], errors="replace").read()
print(sum(map(int, re.findall(r"prefetchit-inject: injected=([0-9]+)", text))))
PY
)"
  linked_prefetches="$(llvm-objdump-19 -d "${binary}" | rg -c '\bprefetcht1\b' || true)"
  linked_prefetches="${linked_prefetches:-0}"
  linked_delta=$((linked_prefetches - baseline_prefetches))
  sha="$(sha256sum "${binary}" | awk '{print $1}')"
  status=ok
  minimum_linked=$(((planned_prefetches * 9 + 9) / 10))
  if ((linked_delta < minimum_linked)); then
    status=missing-injection
  fi
  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "${label}" "${status}" "${planned_injections}" "${planned_prefetches}" \
    "${logged_injections}" "${baseline_prefetches}" "${linked_prefetches}" \
    "${linked_delta}" "${validator_rc}" "${sha}" "${binary}" "${plugin}" \
    | tee -a "${OUT}/build_summary.csv"
  [[ "${status}" == ok ]]
done
