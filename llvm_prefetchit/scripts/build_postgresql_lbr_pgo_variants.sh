#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "usage: $0 PLAN_VARIANTS_DIR OUT_DIR" >&2
  exit 2
fi

ROOT="/home/hnpark2/prefetchit/llvm_prefetchit"
UPSTREAM="${POSTGRES_SRC:-/home/hnpark2/prefetchit/benchmarks/datacenter_sources/postgres}"
BASE_INSTALL="${POSTGRES_BASE_INSTALL:-${ROOT}/work/datacenter_goal_20260708/postgres/install_base}"
PASS="${PASS:-${ROOT}/build/PrefetchITPass.so}"
PLANS="$(readlink -f "$1")"
OUT="$(readlink -m "$2")"
JOBS="${JOBS:-6}"
VARIANTS="${BUILD_VARIANTS:-cov25_d1_32_b4_o0 cov25_d1_32_b4_o064 cov50_d1_32_b4_o0 cov50_d1_32_b4_o064 cov75_d1_32_b4_o0 cov75_d1_32_b4_o064 cov100_d1_32_b4_o0 cov100_d1_32_b4_o064 cov100_d1_8_b16_o0}"
BUILD_ROOT="${BUILD_ROOT:-${OUT}/build}"
SRC="${BUILD_ROOT}/src"
SOURCE_REV="${SOURCE_REV:-$(git -C "${UPSTREAM}" rev-parse HEAD)}"

[[ -x "${BASE_INSTALL}/bin/postgres" && -f "${PASS}" ]]
mkdir -p "${OUT}" "${BUILD_ROOT}"

current_revision=""
if [[ -f "${SRC}/.prefetchit-source-revision" ]]; then
  current_revision="$(<"${SRC}/.prefetchit-source-revision")"
fi
if [[ "${current_revision}" != "${SOURCE_REV}" ]]; then
  if [[ -e "${SRC}" ]]; then
    echo "refusing to replace mismatched source tree: ${SRC}" >&2
    exit 1
  fi
  mkdir -p "${SRC}"
  git -C "${UPSTREAM}" archive "${SOURCE_REV}" | tar -x -C "${SRC}"
  printf '%s\n' "${SOURCE_REV}" > "${SRC}/.prefetchit-source-revision"
fi

if [[ ! -f "${SRC}/GNUmakefile" ]]; then
  (
    cd "${SRC}"
    CC=clang CFLAGS="-O3 -g -fno-omit-frame-pointer -ffile-prefix-map=${SRC}=${UPSTREAM}" \
      ./configure --prefix="${BUILD_ROOT}/install" --without-icu \
        --without-readline --without-zlib
  ) > "${OUT}/configure.log" 2>&1
fi

if [[ ! -f "${BUILD_ROOT}/.baseline-build-complete" ]]; then
  make -C "${SRC}" clean > "${OUT}/build_baseline_dependencies.log" 2>&1
  make -C "${SRC}/src/backend" generated-headers \
    >> "${OUT}/build_baseline_dependencies.log" 2>&1
  make -C "${SRC}" -j"${JOBS}" \
    >> "${OUT}/build_baseline_dependencies.log" 2>&1
  touch "${BUILD_ROOT}/.baseline-build-complete"
fi

printf 'label,status,planned_injections,planned_prefetches,assembly_prefetches,sha256,prefix,binary\n' \
  > "${OUT}/build_summary.csv"

make_prefix() {
  local label="$1" prefix="${OUT}/installs/${label}"
  if [[ ! -d "${prefix}" ]]; then
    mkdir -p "$(dirname "${prefix}")"
    cp -al "${BASE_INSTALL}" "${prefix}"
  fi
  printf '%s\n' "${prefix}"
}

build_one() {
  local label="$1" plan="$2" log prefix binary
  log="${OUT}/build_${label}.log"
  prefix="$(make_prefix "${label}")"
  binary="${prefix}/bin/postgres"

  make -C "${SRC}/src/backend" clean > "${log}" 2>&1
  make -C "${SRC}/src/backend" generated-headers >> "${log}" 2>&1
  rm -f "${SRC}"/src/common/*_srv.o "${SRC}/src/common/libpgcommon_srv.a"
  rm -f "${SRC}"/src/port/*_srv.o "${SRC}/src/port/libpgport_srv.a"
  PREFETCHIT_PLAN="${plan}" make -C "${SRC}/src/common" -j"${JOBS}" \
    libpgcommon_srv.a CUSTOM_COPT="-fpass-plugin=${PASS}" >> "${log}" 2>&1
  PREFETCHIT_PLAN="${plan}" make -C "${SRC}/src/port" -j"${JOBS}" \
    libpgport_srv.a CUSTOM_COPT="-fpass-plugin=${PASS}" >> "${log}" 2>&1
  PREFETCHIT_PLAN="${plan}" make -C "${SRC}/src/backend" -j"${JOBS}" postgres \
    CUSTOM_COPT="-fpass-plugin=${PASS}" >> "${log}" 2>&1
  rm -f "${binary}"
  cp -p "${SRC}/src/backend/postgres" "${binary}"

  local planned_injections planned_prefetches assembly_prefetches sha
  planned_injections="$(jq -r '.stats.selected_injections' "${plan}")"
  planned_prefetches="$(jq -r '.stats.planned_prefetches' "${plan}")"
  assembly_prefetches="$(objdump -d "${binary}" 2>/dev/null | rg -c '\bprefetcht1\b' || true)"
  assembly_prefetches="${assembly_prefetches:-0}"
  sha="$(sha256sum "${binary}" | awk '{print $1}')"
  printf '%s,ok,%s,%s,%s,%s,%s,%s\n' \
    "${label}" "${planned_injections}" "${planned_prefetches}" \
    "${assembly_prefetches}" "${sha}" "${prefix}" "${binary}" \
    | tee -a "${OUT}/build_summary.csv"
}

for label in ${VARIANTS}; do
  plan="${PLANS}/${label}/prefetchit.plan.json"
  [[ -s "${plan}" ]] || { echo "missing plan: ${plan}" >&2; exit 2; }
  build_one "${label}" "${plan}"
done
