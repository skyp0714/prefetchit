#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_COMMON="${SCRIPT_DIR}/../bench/bench_common.sh"
PATCH_TOOL="${SCRIPT_DIR}/apply_prefetchit_variant_patch.py"

usage() {
  cat <<'USAGE'
Usage: launch_prefetchit_builds.sh --variant-root <dir> --config <Config> --output-root <dir> [options]

Options:
  --variant-root <dir>   Root containing prepared variant dirs
  --variant-prefix <s>   Prefix for variant dir names (default: verilator_pf_)
  --variants-file <path> CSV/flat file to specify variant_short list (e.g., variant_dirs.csv)
                         If omitted, defaults to baseline,d2,d4,d8,d16,d32.
  --config <Config>      Chipyard config class (e.g., DualMegaBoomAndSingleRocketConfig)
  --output-root <dir>    Output root for logs/binaries
  --gap-sec <N>          Start gap between jobs in seconds (default: 600)
  --clean-mode <mode>    Build clean mode: none|clean (default: none)
  --prefetch-result-root <dir>
                         If set, apply prefetch patch after model generation using this result dir
  --patch-tool <path>    Patch tool used with --prefetch-result-root
                         (default: apply_prefetchit_variant_patch.py)
  --cc <bin>             C compiler (default: clang-19)
  --cxx <bin>            C++ compiler (default: clang++-19)
  --link <bin>           Linker compiler (default: clang++-19)
  --extra-cxxflags <s>   EXTRA_SIM_CXXFLAGS (default: -g -fno-omit-frame-pointer -std=c++20 -Wno-c++11-narrowing)
  --jobs <N>             make -j value (default: nproc)
USAGE
}

VARIANT_ROOT=""
VARIANT_PREFIX="verilator_pf_"
VARIANTS_FILE=""
CONFIG=""
OUTPUT_ROOT=""
GAP_SEC=600
CLEAN_MODE="none"
PREFETCH_RESULT_ROOT=""
CC_BIN="clang-19"
CXX_BIN="clang++-19"
LINK_BIN="clang++-19"
EXTRA_CXXFLAGS="-g -fno-omit-frame-pointer -std=c++20 -Wno-c++11-narrowing"
JOBS="$(nproc)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --variant-root)
      VARIANT_ROOT="${2:-}"
      shift 2
      ;;
    --variant-prefix)
      VARIANT_PREFIX="${2:-}"
      shift 2
      ;;
    --variants-file)
      VARIANTS_FILE="${2:-}"
      shift 2
      ;;
    --config)
      CONFIG="${2:-}"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="${2:-}"
      shift 2
      ;;
    --gap-sec)
      GAP_SEC="${2:-}"
      shift 2
      ;;
    --clean-mode)
      CLEAN_MODE="${2:-}"
      shift 2
      ;;
    --prefetch-result-root)
      PREFETCH_RESULT_ROOT="${2:-}"
      shift 2
      ;;
    --patch-tool)
      PATCH_TOOL="${2:-}"
      shift 2
      ;;
    --cc)
      CC_BIN="${2:-}"
      shift 2
      ;;
    --cxx)
      CXX_BIN="${2:-}"
      shift 2
      ;;
    --link)
      LINK_BIN="${2:-}"
      shift 2
      ;;
    --extra-cxxflags)
      EXTRA_CXXFLAGS="${2:-}"
      shift 2
      ;;
    --jobs)
      JOBS="${2:-}"
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

if [[ -z "${VARIANT_ROOT}" || -z "${CONFIG}" || -z "${OUTPUT_ROOT}" ]]; then
  usage
  exit 1
fi
if [[ ! -f "${BENCH_COMMON}" ]]; then
  echo "[err] missing bench_common.sh: ${BENCH_COMMON}" >&2
  exit 1
fi
if [[ -n "${PREFETCH_RESULT_ROOT}" && ! -f "${PATCH_TOOL}" ]]; then
  echo "[err] missing patch tool: ${PATCH_TOOL}" >&2
  exit 1
fi

if ! [[ "${GAP_SEC}" =~ ^[0-9]+$ ]]; then
  echo "[err] --gap-sec must be non-negative integer" >&2
  exit 1
fi
if ! [[ "${JOBS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[err] --jobs must be positive integer" >&2
  exit 1
fi
if [[ "${CLEAN_MODE}" != "none" && "${CLEAN_MODE}" != "clean" ]]; then
  echo "[err] --clean-mode must be one of: none, clean" >&2
  exit 1
fi

mkdir -p "${OUTPUT_ROOT}/logs" "${OUTPUT_ROOT}/binaries"

default_variants=(baseline d2 d4 d8 d16 d32)
variants=()

if [[ -n "${VARIANTS_FILE}" ]]; then
  if [[ ! -f "${VARIANTS_FILE}" ]]; then
    echo "[err] variants file not found: ${VARIANTS_FILE}" >&2
    exit 1
  fi

  # Accept either:
  # 1) CSV with header: variant,variant_short,...
  # 2) plain list (one variant short name per line)
  while IFS= read -r v; do
    [[ -z "${v}" ]] && continue
    variants+=("${v}")
  done < <(
    awk -F, '
      NR==1 {
        hdr1=$1; hdr2=$2;
        if (hdr1=="variant" && hdr2=="variant_short") {
          mode="csv2";
          next;
        }
      }
      {
        if (mode=="csv2") {
          gsub(/^[ \t]+|[ \t]+$/, "", $2);
          if ($2 != "") print $2;
        } else {
          line=$0;
          gsub(/^[ \t]+|[ \t]+$/, "", line);
          if (line != "" && line !~ /^#/) {
            split(line, a, ",");
            gsub(/^[ \t]+|[ \t]+$/, "", a[1]);
            if (a[1] != "") print a[1];
          }
        }
      }
    ' "${VARIANTS_FILE}"
  )
else
  variants=("${default_variants[@]}")
fi

if [[ ${#variants[@]} -eq 0 ]]; then
  echo "[err] no variants parsed" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
manifest="${OUTPUT_ROOT}/build_launch_manifest_${timestamp}.csv"
echo "variant,variant_prefixed,session,variant_dir,delay_sec,log_path,binary_out" > "${manifest}"

for i in "${!variants[@]}"; do
  v="${variants[$i]}"
  vp="${VARIANT_PREFIX}${v}"
  vdir="${VARIANT_ROOT}/${vp}"
  if [[ ! -d "${vdir}" ]]; then
    echo "[err] missing variant dir: ${vdir}" >&2
    exit 1
  fi

  delay=$((i * GAP_SEC))
  session="pfbuild_${vp}_${timestamp}"
  log="${OUTPUT_ROOT}/logs/${vp}.log"
  outbin="${OUTPUT_ROOT}/binaries/simulator-chipyard.harness-${CONFIG}-${vp}"

  if [[ "${CLEAN_MODE}" == "clean" ]]; then
    clean_cmd="make clean 2>&1 | tee -a '${log}'"
  else
    clean_cmd="echo '[inf] skip make clean (preserve local state)' | tee -a '${log}'"
  fi

  cmd="$(cat <<EOF2
sleep ${delay}
source '${BENCH_COMMON}'
setup_verilator_env
cd '${vdir}'
echo '[run] variant=${vp} start='"\$(date)" | tee '${log}'
${clean_cmd}
model_mk="\$(make CONFIG='${CONFIG}' CC='${CC_BIN}' CXX='${CXX_BIN}' LINK='${LINK_BIN}' EXTRA_SIM_CXXFLAGS='${EXTRA_CXXFLAGS}' --eval='print-model-mk: ; @echo \$(model_mk)' -s print-model-mk)"
sim_target="\$(make CONFIG='${CONFIG}' CC='${CC_BIN}' CXX='${CXX_BIN}' LINK='${LINK_BIN}' EXTRA_SIM_CXXFLAGS='${EXTRA_CXXFLAGS}' --eval='print-sim-target: ; @echo \$(sim)' -s print-sim-target)"
if [[ -z "\${model_mk}" || -z "\${sim_target}" ]]; then
  echo '[err] failed to resolve model_mk/sim target from make -pn' | tee -a '${log}'
  exit 1
fi
model_dir="\$(dirname "\${model_mk}")"
echo "[inf] model_mk=\${model_mk}" | tee -a '${log}'
echo "[inf] model_dir=\${model_dir}" | tee -a '${log}'
echo "[inf] sim_target=\${sim_target}" | tee -a '${log}'
if [[ -n '${PREFETCH_RESULT_ROOT}' ]]; then
  echo "[inf] force regenerate model_mk so embedded simulator path matches this variant" | tee -a '${log}'
  rm -f "\${model_mk}"
fi
make CONFIG='${CONFIG}' CC='${CC_BIN}' CXX='${CXX_BIN}' LINK='${LINK_BIN}' EXTRA_SIM_CXXFLAGS='${EXTRA_CXXFLAGS}' "\${model_mk}" -j'${JOBS}' 2>&1 | tee -a '${log}'
if [[ -f "\${model_mk}" ]] && ! rg -F "default: \${sim_target}" "\${model_mk}" >/dev/null 2>&1; then
  echo "[err] regenerated model_mk does not target expected simulator: \${sim_target}" | tee -a '${log}'
  rg -n '^default:|/simulator-chipyard' "\${model_mk}" | head -20 | tee -a '${log}' || true
  exit 1
fi
if [[ -n '${PREFETCH_RESULT_ROOT}' ]]; then
  python3 '${PATCH_TOOL}' --variant-dir '${vdir}' --variant-short '${v}' --config '${CONFIG}' --result-root '${PREFETCH_RESULT_ROOT}' 2>&1 | tee -a '${log}'
  src_prefetch_count="\$( (rg -uuu -o 'prefetchit0|prefetcht0' "\${model_dir}" 2>/dev/null || true) | wc -l | tr -d ' ' )"
  echo "[inf] source_prefetchit_count_after_patch=\${src_prefetch_count}" | tee -a '${log}'
fi
rm -f "\${model_dir}/VTestDriver__ALL.o" "\${model_dir}/VTestDriver__ALL.a" "\${model_dir}/VTestDriver__ALL.d" "\${sim_target}"
make CONFIG='${CONFIG}' CC='${CC_BIN}' CXX='${CXX_BIN}' LINK='${LINK_BIN}' EXTRA_SIM_CXXFLAGS='${EXTRA_CXXFLAGS}' "\${sim_target}" -j'${JOBS}' 2>&1 | tee -a '${log}'
cp -f "\${sim_target}" '${outbin}'
echo '[ok] variant=${vp} done='"\$(date)" | tee -a '${log}'
EOF2
)"

  tmux new-session -d -s "${session}" "bash -lc ${cmd@Q}"
  echo "${v},${vp},${session},${vdir},${delay},${log},${outbin}" >> "${manifest}"
  echo "[launched] ${vp} session=${session} delay=${delay}s"
done

echo
echo "[ok] launch manifest: ${manifest}"
ln -sfn "$(basename "${manifest}")" "${OUTPUT_ROOT}/latest_manifest.csv"
echo "[ok] latest manifest: ${OUTPUT_ROOT}/latest_manifest.csv"
echo "[tip] monitor: tmux ls | grep pfbuild_"
echo "[tip] logs: ${OUTPUT_ROOT}/logs/*.log"
