#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 3 || "$#" -gt 4 ]]; then
  echo "usage: $0 router|setalgebra baseline|pgo OUT_DIR [PLAN]" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit/llvm_prefetchit"
BENCHMARK="$1"
MODE="$2"
OUT="$(readlink -m "$3")"
PLAN="${4:-}"
SOURCE="${ROOT}/experiments/microsuite_static_grpc"
PASS="${PASS:-${ROOT}/build/PrefetchITPass.so}"
JOBS="${JOBS:-12}"
GRPC_MAX_THREADS="${GRPC_MAX_THREADS:-4}"
GRPC_CLIENT_MAX_THREADS="${GRPC_CLIENT_MAX_THREADS:-4}"

case "${BENCHMARK}" in
  router|setalgebra) ;;
  *) echo "unsupported benchmark: ${BENCHMARK}" >&2; exit 2 ;;
esac
case "${MODE}" in
  baseline)
    [[ -z "${PLAN}" ]] || { echo "baseline mode does not take a plan" >&2; exit 2; }
    ;;
  pgo)
    PLAN="$(readlink -f "${PLAN}")"
    [[ -s "${PLAN}" && -s "${PASS}" ]] || {
      echo "missing PGO plan or pass plugin" >&2
      exit 2
    }
    ;;
  *) echo "unsupported mode: ${MODE}" >&2; exit 2 ;;
esac

rm -rf "${OUT}"
mkdir -p "${OUT}"
configure=(
  cmake -S "${SOURCE}" -B "${OUT}" -G Ninja
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
  -DCMAKE_C_COMPILER=clang-19
  -DCMAKE_CXX_COMPILER=clang++-19
  "-DPREFETCHIT_BENCHMARK=${BENCHMARK}"
  "-DPREFETCHIT_GRPC_MAX_THREADS=${GRPC_MAX_THREADS}"
  "-DPREFETCHIT_GRPC_CLIENT_MAX_THREADS=${GRPC_CLIENT_MAX_THREADS}"
)
if [[ "${MODE}" == pgo ]]; then
  configure+=("-DPREFETCHIT_PASS_PLUGIN=${PASS}")
fi
"${configure[@]}" 2>&1 | tee "${OUT}/configure.log"

if [[ "${MODE}" == pgo ]]; then
  PREFETCHIT_PLAN="${PLAN}" \
    cmake --build "${OUT}" --target microsuite_mid_tier -j "${JOBS}" 2>&1 \
    | tee "${OUT}/build.log"
else
  env -u PREFETCHIT_PLAN \
    cmake --build "${OUT}" --target microsuite_mid_tier -j "${JOBS}" 2>&1 \
    | tee "${OUT}/build.log"
fi

binary="${OUT}/mid_tier_server"
[[ -x "${binary}" ]] || { echo "missing output binary: ${binary}" >&2; exit 1; }
llvm-objdump-19 -d "${binary}" | rg -c '\bprefetch' \
  > "${OUT}/assembly_prefetch_count.txt" || true
sha256sum "${binary}" > "${OUT}/mid_tier_server.sha256"
if [[ "${MODE}" == pgo ]]; then
  rg 'prefetchit-inject: injected=[1-9]' "${OUT}/build.log" \
    > "${OUT}/prefetch_pass.log" || true
else
  : > "${OUT}/prefetch_pass.log"
fi
printf 'benchmark=%s\nmode=%s\nbinary=%s\nplan=%s\ngrpc_max_threads=%s\ngrpc_client_max_threads=%s\n' \
  "${BENCHMARK}" "${MODE}" "${binary}" "${PLAN}" "${GRPC_MAX_THREADS}" \
  "${GRPC_CLIENT_MAX_THREADS}" \
  > "${OUT}/build.conf"
cat "${OUT}/build.conf"
cat "${OUT}/mid_tier_server.sha256"
