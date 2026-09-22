#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LLVM_PREFETCH_DIR="${ROOT_DIR}/llvm_prefetchit"
TAILBENCH_SRC="${ROOT_DIR}/benchmarks/tailbench/tailbench"
TAILBENCH_HOME="${ROOT_DIR}/benchmarks/tailbench"
PROFILING_DIR="${ROOT_DIR}/profiling"

RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${OUT_DIR:-${LLVM_PREFETCH_DIR}/results/tailbench_highmpki_pgo_${RUN_ID}}"
WORK_ROOT="${WORK_ROOT:-${LLVM_PREFETCH_DIR}/work/tailbench_highmpki_pgo_${RUN_ID}}"
BENCHMARKS="${BENCHMARKS:-xapian img_dnn moses sphinx masstree silo shore}"
COVERAGES="${COVERAGES:-10 25 50 75 100}"
PROFILE_REPS="${PROFILE_REPS:-3}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-120}"
RUN_TO_COMPLETION="${RUN_TO_COMPLETION:-0}"
REQUEST_SECONDS="${REQUEST_SECONDS:-120}"
SAMPLE_PERIOD="${SAMPLE_PERIOD:-100000}"
L2_STAT_EVENT="${L2_STAT_EVENT:-cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/}"
L2_RECORD_EVENT="${L2_RECORD_EVENT:-cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/upp}"
PREFETCH_BYTE_OFFSETS="${PREFETCH_BYTE_OFFSETS:-0,64}"
PROFILE_SOURCE_OUT="${PROFILE_SOURCE_OUT:-${OUT_DIR}}"
SKIP_EVAL="${SKIP_EVAL:-0}"
PIN_INTERVAL_SEC="${PIN_INTERVAL_SEC:-0.05}"
JOBS="${JOBS:-16}"

PASS_SO="${LLVM_PREFETCH_DIR}/build/PrefetchITPass.so"
CLANG_BIN="${CLANG_BIN:-clang-19}"
CLANGXX_BIN="${CLANGXX_BIN:-clang++-19}"
ADDR2LINE_BIN="${ADDR2LINE_BIN:-llvm-addr2line-19}"
NM_BIN="${NM_BIN:-nm}"
PERF_BIN="${PERF_BIN:-perf}"

mkdir -p "${OUT_DIR}" "${WORK_ROOT}" "${OUT_DIR}/build_logs"
LOG="${OUT_DIR}/run.log"
BUILD_CSV="${OUT_DIR}/build.csv"
PROFILE_CSV="${OUT_DIR}/profiles.csv"
PLAN_CSV="${OUT_DIR}/plans.csv"
EVAL_DIR="${OUT_DIR}/eval_runs"
SUMMARY_MD="${OUT_DIR}/summary.md"

if [[ ! -f "${BUILD_CSV}" ]]; then
  echo "benchmark,label,status,prefetch_count,workdir,exe,log,note" > "${BUILD_CSV}"
fi
if [[ ! -f "${PROFILE_CSV}" ]]; then
  echo "benchmark,rep,status,trace_dir,samples,top_branch_type,top_branch_pct,top_target,top_target_pct,log" > "${PROFILE_CSV}"
fi
if [[ ! -f "${PLAN_CSV}" ]]; then
  echo "benchmark,coverage,status,plan,injections,selected_targets,parsed_samples,prefetches,log" > "${PLAN_CSV}"
fi

log() {
  printf '[%(%F %T)T] %s\n' -1 "$*" | tee -a "${LOG}"
}

csv_append() {
  python3 - "$@" <<'PY'
import csv
import sys
path = sys.argv[1]
row = sys.argv[2:]
with open(path, "a", newline="") as f:
    csv.writer(f).writerow(row)
PY
}

bench_key() {
  case "$1" in
    img-dnn|img_dnn) echo "img_dnn" ;;
    *) echo "$1" ;;
  esac
}

bench_src_name() {
  case "$(bench_key "$1")" in
    img_dnn) echo "img-dnn" ;;
    *) echo "$(bench_key "$1")" ;;
  esac
}

bench_workdir_rel() {
  bench_src_name "$1"
}

bench_exe_rel() {
  case "$(bench_key "$1")" in
    xapian) echo "xapian/xapian_integrated" ;;
    img_dnn) echo "img-dnn/img-dnn_integrated" ;;
    moses) echo "moses/bin/moses_integrated" ;;
    sphinx) echo "sphinx/decoder_integrated" ;;
    masstree) echo "masstree/mttest_integrated" ;;
    silo) echo "silo/out-perf.masstree/benchmarks/dbtest_integrated" ;;
    shore) echo "shore/shore-kits/shore_kits_integrated" ;;
    specjbb) echo "specjbb/build/dist/jbb.jar" ;;
    *) return 1 ;;
  esac
}

bench_core_range() {
  case "$(bench_key "$1")" in
    xapian) echo "0" ;;
    img_dnn) echo "0-1" ;;
    moses) echo "0-1" ;;
    sphinx) echo "0-1" ;;
    masstree) echo "0-2" ;;
    silo) echo "0-5" ;;
    shore) echo "0-8" ;;
    specjbb) echo "0-23" ;;
    *) echo "0" ;;
  esac
}

bench_qps() {
  case "$(bench_key "$1")" in
    xapian) echo 50 ;;
    img_dnn) echo 500 ;;
    moses) echo 20 ;;
    sphinx) echo 1 ;;
    masstree) echo 2000 ;;
    silo) echo 1000 ;;
    shore) echo 50 ;;
    specjbb) echo 5000 ;;
    *) echo 1 ;;
  esac
}

bench_warmup_reqs() {
  case "$(bench_key "$1")" in
    xapian) echo 1000 ;;
    img_dnn) echo 1000 ;;
    moses) echo 100 ;;
    sphinx) echo 10 ;;
    masstree) echo 1000 ;;
    silo) echo 1000 ;;
    shore) echo 100 ;;
    specjbb) echo 1000 ;;
    *) echo 0 ;;
  esac
}

bench_measured_reqs() {
  local qps
  qps="$(bench_qps "$1")"
  echo $((qps * REQUEST_SECONDS))
}

bench_cmd() {
  local key req warmup qps
  key="$(bench_key "$1")"
  req="$(bench_measured_reqs "${key}")"
  warmup="$(bench_warmup_reqs "${key}")"
  qps="$(bench_qps "${key}")"
  if [[ "${RUN_TO_COMPLETION}" == "1" ]]; then
    case "${key}" in
      xapian)
        echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} NSERVERS=1 QPS=${qps} WARMUPREQS=${warmup} REQUESTS=${req} bash ./run.sh"
        ;;
      img_dnn)
        echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/apt_opencv/root/usr/lib/x86_64-linux-gnu:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=1 QPS=${qps} WARMUPREQS=${warmup} MAXREQS=${req} REQS=100000000 bash ./run.sh"
        ;;
      moses)
        echo "LD_LIBRARY_PATH=./bin:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=1 QPS=${qps} WARMUPREQS=${warmup} MAXREQS=${req} bash ./run.sh"
        ;;
      sphinx)
        echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=1 QPS=${qps} WARMUPREQS=${warmup} MAXREQS=${req} bash ./run.sh"
        ;;
      masstree)
        echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} NTHREADS=1 QPS=${qps} WARMUPREQS=${warmup} MAXREQS=${req} bash ./run.sh"
        ;;
      silo)
        echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/apt_silo/root/usr/lib/x86_64-linux-gnu:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} NUM_THREADS=1 NUM_WAREHOUSES=1 QPS=${qps} WARMUPREQS=${warmup} MAXREQS=${req} bash ./run.sh"
        ;;
      shore)
        echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=1 QPS=${qps} WARMUPREQS=${warmup} MAXREQS=${req} DUMMYREQS=100000000 bash ./run.sh"
        ;;
      specjbb)
        echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} GC_THREADS=1 QPS=${qps} WARMUPREQS=${warmup} MAXREQS=${req} bash ./run.sh"
        ;;
      *) return 1 ;;
    esac
    return 0
  fi

  case "${key}" in
    xapian)
      echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} NSERVERS=1 QPS=50 WARMUPREQS=1000 REQUESTS=100000000 bash ./run.sh"
      ;;
    img_dnn)
      echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/apt_opencv/root/usr/lib/x86_64-linux-gnu:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=1 QPS=500 WARMUPREQS=1000 MAXREQS=100000000 REQS=100000000 bash ./run.sh"
      ;;
    moses)
      echo "LD_LIBRARY_PATH=./bin:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=1 QPS=20 WARMUPREQS=100 MAXREQS=100000000 bash ./run.sh"
      ;;
    sphinx)
      echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=1 QPS=1 WARMUPREQS=10 MAXREQS=100000000 bash ./run.sh"
      ;;
    masstree)
      echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} NTHREADS=1 QPS=2000 WARMUPREQS=1000 MAXREQS=100000000 bash ./run.sh"
      ;;
    silo)
      echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/apt_silo/root/usr/lib/x86_64-linux-gnu:${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} NUM_THREADS=1 NUM_WAREHOUSES=1 QPS=1000 WARMUPREQS=1000 MAXREQS=100000000 bash ./run.sh"
      ;;
    shore)
      echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} THREADS=1 QPS=50 WARMUPREQS=100 MAXREQS=100000000 DUMMYREQS=100000000 bash ./run.sh"
      ;;
    specjbb)
      echo "LD_LIBRARY_PATH=${TAILBENCH_HOME}/.local/deps/lib:/usr/local/lib:\${LD_LIBRARY_PATH:-} GC_THREADS=1 QPS=5000 WARMUPREQS=1000 MAXREQS=100000000 bash ./run.sh"
      ;;
    *) return 1 ;;
  esac
}

expand_core_list() {
  python3 - "$1" <<'PY'
import sys
out = []
seen = set()
for part in sys.argv[1].split(","):
    part = part.strip()
    if not part:
        continue
    if "-" in part:
        lo, hi = [int(x) for x in part.split("-", 1)]
        step = 1 if lo <= hi else -1
        vals = range(lo, hi + step, step)
    else:
        vals = [int(part)]
    for v in vals:
        if v not in seen:
            seen.add(v)
            out.append(v)
print(" ".join(map(str, out)))
PY
}

start_pinner() {
  local root_pid="$1"
  local cores="$2"
  local pin_log="$3"
  (
    declare -A tid_to_core=()
    next_core_idx=0
    read -r -a pin_cores <<< "$(expand_core_list "${cores}")"
    ignored_re='^(perf|taskset|sleep|ps|awk|pgrep|sed|tr|tee|time|python3?)$'
    wrapper_re='^(timeout|bash|sh)$'
    while :; do
      pids="${root_pid}"
      frontier="${root_pid}"
      while [[ -n "${frontier}" ]]; do
        next=""
        for parent in ${frontier}; do
          children="$(pgrep -P "${parent}" 2>/dev/null || true)"
          if [[ -n "${children}" ]]; then
            next="${next} ${children}"
            pids="${pids} ${children}"
          fi
        done
        frontier="${next}"
      done
      pid_csv="$(tr ' ' ',' <<< "${pids}" | sed 's/^,*//; s/,*$//; s/,,*/,/g')"
      while read -r pid tid comm; do
        [[ -n "${tid}" ]] || continue
        if [[ "${comm}" =~ ${ignored_re} ]]; then
          continue
        fi
        if [[ "${comm}" =~ ${wrapper_re} ]]; then
          core="${pin_cores[0]}"
          if [[ -z "${tid_to_core[${tid}]:-}" ]]; then
            tid_to_core["${tid}"]="${core}"
            printf '[%(%F %T)T] assign-wrapper tid=%s pid=%s comm=%s core=%s\n' -1 "${tid}" "${pid}" "${comm}" "${core}" >> "${pin_log}"
          fi
        else
          core="${tid_to_core[${tid}]:-}"
        fi
        if [[ -z "${core}" ]]; then
          core="${pin_cores[$((next_core_idx % ${#pin_cores[@]}))]}"
          tid_to_core["${tid}"]="${core}"
          next_core_idx=$((next_core_idx + 1))
          printf '[%(%F %T)T] assign tid=%s pid=%s comm=%s core=%s\n' -1 "${tid}" "${pid}" "${comm}" "${core}" >> "${pin_log}"
        fi
        taskset -pc "${core}" "${tid}" >/dev/null 2>&1 || true
      done < <(ps -eLo pid,tid,comm,args 2>/dev/null | awk -v pids="${pid_csv}" '
        BEGIN {
          split(pids, c, ",")
          for (i in c) if (c[i] != "") allow[c[i]] = 1
        }
        NR > 1 && allow[$1] { print $1, $2, $3 }
      ')
      sleep "${PIN_INTERVAL_SEC}"
    done
  ) &
  PINNER_PID="$!"
}

write_wrappers() {
  local dir="$1"
  local plan="${2:-}"
  mkdir -p "${dir}"
  for cc in clang cc gcc clang-prefetchit; do
    {
      echo "#!/usr/bin/env bash"
      if [[ -n "${plan}" ]]; then
        echo "export PREFETCHIT_PLAN=\"${plan}\""
        echo "exec ${CLANG_BIN} -fpass-plugin=\"${PASS_SO}\" \"\$@\""
      else
        echo "exec ${CLANG_BIN} \"\$@\""
      fi
    } > "${dir}/${cc}"
    chmod +x "${dir}/${cc}"
  done
  for cxx in clang++ c++ g++ clangxx-prefetchit; do
    {
      echo "#!/usr/bin/env bash"
      if [[ -n "${plan}" ]]; then
        echo "export PREFETCHIT_PLAN=\"${plan}\""
        echo "exec ${CLANGXX_BIN} -fpass-plugin=\"${PASS_SO}\" \"\$@\""
      else
        echo "exec ${CLANGXX_BIN} \"\$@\""
      fi
    } > "${dir}/${cxx}"
    chmod +x "${dir}/${cxx}"
  done
}

write_configs() {
  local td="$1"
  cat > "${td}/configs.sh" <<EOF
TAILBENCH_ROOT="${td}"
TAILBENCH_HOME="${TAILBENCH_HOME}"
DATA_ROOT="${TAILBENCH_HOME}/tailbench.inputs"
if [[ -d "${TAILBENCH_HOME}/.local/jdk8" ]]; then
    JDK_PATH="${TAILBENCH_HOME}/.local/jdk8"
elif [[ -d /usr/lib/jvm/java-8-openjdk-amd64 ]]; then
    JDK_PATH=/usr/lib/jvm/java-8-openjdk-amd64
else
    JDK_PATH=/usr/lib/jvm/java-11-openjdk-amd64
fi
SCRATCH_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")/.." && pwd)/scratch"
mkdir -p "\${SCRATCH_DIR}"
EOF
  cat > "${td}/Makefile.config" <<EOF
JDK_PATH=${TAILBENCH_HOME}/.local/jdk8
EOF
}

rsync_clean_source() {
  local src="$1"
  local dst="$2"
  shift 2
  mkdir -p "$(dirname "${dst}")"
  rsync -a --delete \
    --exclude '*.o' --exclude '*.d' --exclude '*.a' --exclude '*.so' \
    --exclude '*.class' --exclude '.deps' --exclude 'autom4te.cache' \
    --exclude 'build.log' --exclude 'clean.log' --exclude 'lats.bin' \
    --exclude '*_integrated' --exclude '*_server_networked' \
    --exclude '*_client_networked' --exclude 'genTerms' --exclude 'train' \
    --exclude 'decoder_integrated' --exclude 'decoder_server_networked' \
    --exclude 'decoder_client_networked' \
    "$@" "${src}/" "${dst}/"
}

patch_silo_for_clang() {
  local dir="$1"
  python3 - "${dir}" <<'PY'
from pathlib import Path
root = Path(__import__("sys").argv[1])
db = root / "benchmarks" / "dbtest.cc"
text = db.read_text()
old = """  vector<string> bench_toks = split_ws(bench_opts);
  int argc = 1 + bench_toks.size();
  char *argv[argc];
  argv[0] = (char *) bench_type.c_str();
  for (size_t i = 1; i <= bench_toks.size(); i++)
    argv[i] = (char *) bench_toks[i - 1].c_str();
  test_fn(db, argc, argv);
"""
new = """  vector<string> bench_toks = split_ws(bench_opts);
  int bench_argc = 1 + bench_toks.size();
  std::vector<char *> bench_argv(bench_argc);
  bench_argv[0] = (char *) bench_type.c_str();
  for (size_t i = 1; i <= bench_toks.size(); i++)
    bench_argv[i] = (char *) bench_toks[i - 1].c_str();
  test_fn(db, bench_argc, bench_argv.data());
"""
if old in text:
    db.write_text(text.replace(old, new))
util = root / "util.h"
text = util.read_text()
decl = "template <typename A, typename B>\nstd::ostream &operator<<(std::ostream &o, const std::pair<A, B> &p);\n"
if decl not in text:
    text = text.replace('#include "small_vector.h"\n\nnamespace util {',
                        '#include "small_vector.h"\n\n' + decl + "\nnamespace util {", 1)
    util.write_text(text)
mk = root / "Makefile"
text = mk.read_text()
text = text.replace("cd masstree; ./configure $(MASSTREE_CONFIG)",
                    "cd masstree; CFLAGS= CXXFLAGS= ./configure $(MASSTREE_CONFIG)")
mk.write_text(text)
PY
}

patch_moses_for_clang() {
  local dir="$1"
  python3 - "${dir}" <<'PY'
from pathlib import Path
root = Path(__import__("sys").argv[1])
p = root / "moses" / "ObjectPool.h"
text = p.read_text()
text = text.replace("for(; b!=e; ++b) this->free(*b);", "for(; b!=e; ++b) freeObject(*b);")
p.write_text(text)
PY
}

patch_img_dnn_for_clang() {
  local dir="$1"
  python3 - "${dir}" <<'PY'
from pathlib import Path
root = Path(__import__("sys").argv[1])
for p in [root / "common.h", root / "client.cpp", root / "img-dnn.cpp", root / "train.cpp"]:
    if not p.exists():
        continue
    text = p.read_text()
    text = text.replace('#include "opencv2/highgui/highgui.hpp"\n', "")
    text = text.replace("CV_REDUCE_SUM", "cv::REDUCE_SUM")
    text = text.replace("CV_REDUCE_MAX", "cv::REDUCE_MAX")
    p.write_text(text)
PY
}

patch_shore_for_clang() {
  local dir="$1"
  python3 - "${dir}" <<'PY'
from pathlib import Path
root = Path(__import__("sys").argv[1])
p = root / "shore-mt" / "src" / "sm" / "sm_io.h"
text = p.read_text()
old = """    friend rc_t vol_io_shared::io_lock_force( const lockid_t&         n, 
                    lock_mode_t             m, 
                    lock_duration_t         d, 
                    timeout_in_ms           timeout,  
                    lock_mode_t*            prev_mode = 0, 
                    lock_mode_t*            prev_pgmode = 0, 
                    lockid_t**              nameInLockHead = 0 
                    );
"""
new = """    friend rc_t vol_io_shared::io_lock_force( const lockid_t&         n, 
                    lock_mode_t             m, 
                    lock_duration_t         d, 
                    timeout_in_ms           timeout,  
                    lock_mode_t*            prev_mode, 
                    lock_mode_t*            prev_pgmode, 
                    lockid_t**              nameInLockHead 
                    );
"""
if old in text:
    p.write_text(text.replace(old, new))
tpch = root / "shore-kits" / "include" / "workload" / "tpch" / "shore_tpch_env.h"
text = tpch.read_text()
needle = """    }
    
    return (RCOK);
}

template<class T1_man, class T2_man, class T1_desc, class T2_desc>
"""
replacement = """    }
    
 done:
    return (RCOK);
}

template<class T1_man, class T2_man, class T1_desc, class T2_desc>
"""
if needle in text:
    tpch.write_text(text.replace(needle, replacement, 1))
deps = root / "shore-mt" / "src" / "atomic_ops" / ".deps"
deps.mkdir(parents=True, exist_ok=True)
(deps / "atomic_ops.Po").write_text("""atomic_ops.o: atomic_ops.S /usr/include/stdc-predef.h \\
 ../../config/shore-config.h atomic_ops/amd64/atomic.s \\
 intel/sys/asm_linkage.h ia32/sys/asm_linkage.h intel/sys/stack.h \\
 ia32/sys/stack.h intel/sys/trap.h ia32/sys/trap.h

/usr/include/stdc-predef.h:

../../config/shore-config.h:

atomic_ops/amd64/atomic.s:

intel/sys/asm_linkage.h:

ia32/sys/asm_linkage.h:

intel/sys/stack.h:

ia32/sys/stack.h:

intel/sys/trap.h:

ia32/sys/trap.h:
""")
for rel in ["shore-mt/build.sh", "shore-kits/build.sh"]:
    s = root / rel
    text = s.read_text()
    if not text.startswith("#!/"):
        text = "#!/bin/bash\n" + text
    if "set -e\n" not in text.splitlines()[:4]:
        text = text.replace("#!/bin/bash\n", "#!/bin/bash\nset -e\n", 1)
    text = text.replace('export CXXFLAGS="-std=c++98 -g"', 'export CXX="clang++ -std=gnu++98"\nexport CXXFLAGS="-g -Wno-register"')
    text = text.replace("make -j32", "make -j1")
    s.write_text(text)
PY
}

setup_workdir() {
  local bench="$1"
  local label="$2"
  local plan="${3:-}"
  local key src_name work td wrappers
  key="$(bench_key "${bench}")"
  src_name="$(bench_src_name "${bench}")"
  work="${WORK_ROOT}/${key}_${label}"
  td="${work}/tailbench"
  wrappers="${work}/wrappers"
  rm -rf "${work}"
  mkdir -p "${td}" "${work}/scratch"
  write_wrappers "${wrappers}" "${plan}"
  write_configs "${td}"
  rsync_clean_source "${TAILBENCH_SRC}/harness" "${td}/harness"
  case "${key}" in
    xapian)
      rsync_clean_source "${TAILBENCH_SRC}/${src_name}" "${td}/${src_name}" --exclude 'xapian-core-1.2.13'
      ;;
    img_dnn)
      rsync_clean_source "${TAILBENCH_SRC}/${src_name}" "${td}/${src_name}" --exclude 'models'
      ln -s "${TAILBENCH_SRC}/${src_name}/models" "${td}/${src_name}/models"
      patch_img_dnn_for_clang "${td}/${src_name}"
      ;;
    sphinx)
      rsync_clean_source "${TAILBENCH_SRC}/${src_name}" "${td}/${src_name}" --exclude 'sphinxbase-5prealpha' --exclude 'pocketsphinx-5prealpha' --exclude 'sphinx-install'
      ln -s "${TAILBENCH_SRC}/${src_name}/sphinx-install" "${td}/${src_name}/sphinx-install"
      ;;
    moses)
      rsync_clean_source "${TAILBENCH_SRC}/${src_name}" "${td}/${src_name}" --exclude 'bin'
      patch_moses_for_clang "${td}/${src_name}"
      ;;
    silo)
      rsync_clean_source "${TAILBENCH_SRC}/${src_name}" "${td}/${src_name}" --exclude 'out-*'
      patch_silo_for_clang "${td}/${src_name}"
      ;;
    shore)
      rsync_clean_source "${TAILBENCH_SRC}/${src_name}" "${td}/${src_name}" --exclude 'scratch' --exclude 'log' --exclude 'diskrw' --exclude 'shore-kits/shore_kits_*'
      rsync -a --include '*/' --include '.deps/***' --exclude '*' \
        "${TAILBENCH_SRC}/${src_name}/shore-mt/src/" "${td}/${src_name}/shore-mt/src/"
      patch_shore_for_clang "${td}/${src_name}"
      ;;
    masstree|specjbb)
      rsync_clean_source "${TAILBENCH_SRC}/${src_name}" "${td}/${src_name}"
      ;;
    *)
      log "unknown bench ${bench}"
      return 1
      ;;
  esac
  echo "${work}"
}

build_one() {
  local bench="$1"
  local label="$2"
  local plan="${3:-}"
  local key work td src_name exe_rel exe log_file prefetch_count note rc
  key="$(bench_key "${bench}")"
  src_name="$(bench_src_name "${bench}")"
  log_file="${OUT_DIR}/build_logs/${key}_${label}.log"
  if [[ "${key}" == "specjbb" && "${label}" != "clangbase" ]]; then
    csv_append "${BUILD_CSV}" "${key}" "${label}" "skipped" "" "" "" "${log_file}" "JVM workload; LLVM native pass not applicable"
    return 1
  fi
  log "build ${key} ${label}"
  work="$(setup_workdir "${key}" "${label}" "${plan}")"
  td="${work}/tailbench"
  if declare -F prefetchit_post_setup_hook >/dev/null 2>&1; then
    prefetchit_post_setup_hook "${key}" "${label}" "${work}" "${td}/${src_name}"
  fi
  exe_rel="$(bench_exe_rel "${key}")"
  exe="${td}/${exe_rel}"
  set +e
  (
    export PATH="${work}/wrappers:${PATH}"
    export CC=clang
    export CXX=clang++
    export CXXFLAGS="${CXXFLAGS:-} -Wno-register"
    export CFLAGS="${CFLAGS:-}"
    export LD_LIBRARY_PATH="${TAILBENCH_HOME}/.local/deps/lib:${TAILBENCH_HOME}/.local/apt_libgtop/root/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
    export LD_LIBRARY_PATH="${TAILBENCH_HOME}/.local/apt_opencv/root/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH}"
    export LD_LIBRARY_PATH="${TAILBENCH_HOME}/.local/apt_silo/root/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH}"
    export LIBRARY_PATH="${TAILBENCH_HOME}/.local/apt_silo/root/usr/lib/x86_64-linux-gnu:${TAILBENCH_HOME}/.local/apt_opencv/root/usr/lib/x86_64-linux-gnu:${TAILBENCH_HOME}/.local/apt_libgtop/root/usr/lib/x86_64-linux-gnu:${LIBRARY_PATH:-}"
    export PKG_CONFIG_PATH="${TAILBENCH_HOME}/.local/apt_opencv/root/usr/lib/x86_64-linux-gnu/pkgconfig:${PKG_CONFIG_PATH:-}"
    export CPATH="${TAILBENCH_HOME}/.local/apt_silo/root/usr/include:${TAILBENCH_HOME}/.local/apt_libgtop/root/usr/include/libgtop-2.0:${TAILBENCH_HOME}/.local/apt_libgtop/root/usr/include/glib-2.0:${TAILBENCH_HOME}/.local/apt_libgtop/root/usr/lib/x86_64-linux-gnu/glib-2.0/include:${CPATH:-}"
    cd "${td}/harness"
    make -j"${JOBS}"
    cd "${td}/${src_name}"
    if [[ "${key}" == "moses" ]]; then
      export TBENCH_PATH="${td}/harness"
      export CPATH="${TBENCH_PATH}:${CPATH:-}"
      ./bjam toolset=clang -j"${JOBS}" -q moses-cmd//moses_integrated
      mkdir -p bin
      cp "$(find moses-cmd/bin -type f -name moses_integrated | head -1)" bin/moses_integrated
      find . -path '*/bin/*' -type f -name '*.so' -exec cp {} bin/ \;
    elif [[ "${key}" == "masstree" ]]; then
      autoconf
      ./configure --disable-assertions --with-malloc=jemalloc
      make -j"${JOBS}"
    elif [[ "${key}" == "silo" ]]; then
      MODE=perf MYSQL=0 USE_MALLOC_MODE=1 make -j1 dbtest
    elif [[ "${key}" == "shore" ]]; then
      export CXXFLAGS="-std=gnu++98 -g -Wno-register ${CXXFLAGS:-}"
      cd shore-mt
      ./build.sh
      if [[ -f src/sm/lib/libsm.a && ! -e src/sm/libsm.a ]]; then
        ln -s lib/libsm.a src/sm/libsm.a
      fi
      cd ../shore-kits
      ./build.sh
    else
      ./build.sh
    fi
  ) > "${log_file}" 2>&1
  rc=$?
  set -e
  if [[ "${rc}" -ne 0 || ! -e "${exe}" ]]; then
    note="$(grep -m1 -E '(^|[[:space:]])(fatal error|error):|undefined reference|No such file|not found' "${log_file}" || true)"
    csv_append "${BUILD_CSV}" "${key}" "${label}" "fail" "" "${work}" "${exe}" "${log_file}" "${note}"
    log "build fail ${key} ${label} rc=${rc}"
    return 1
  fi
  prefetch_count=0
  if [[ "${label}" != "clangbase" ]]; then
    prefetch_count="$(llvm-objdump-19 -d -Mintel "${exe}" 2>/dev/null | grep -E -c '\bprefetch(t[012]|nta|it[01])\b' || true)"
  fi
  csv_append "${BUILD_CSV}" "${key}" "${label}" "ok" "${prefetch_count}" "${work}" "${exe}" "${log_file}" ""
  log "build ok ${key} ${label} prefetch_count=${prefetch_count}"
}

profile_one_rep() {
  local bench="$1"
  local rep="$2"
  local work="$3"
  local exe="$4"
  local key src_name workdir command cores trace_dir data_file record_log analyze_log pin_log rc summary samples top_branch top_branch_pct top_target top_target_pct pinner_pid
  key="$(bench_key "${bench}")"
  src_name="$(bench_src_name "${bench}")"
  workdir="${work}/tailbench/${src_name}"
  command="$(bench_cmd "${key}")"
  cores="$(bench_core_range "${key}")"
  trace_dir="${OUT_DIR}/profiles/${key}/rep${rep}/l2_miss"
  data_file="${trace_dir}/l2miss_profile.data"
  record_log="${trace_dir}/record.log"
  analyze_log="${trace_dir}/analyze.log"
  pin_log="${trace_dir}/pin.log"
  mkdir -p "${trace_dir}"
  rm -f "${data_file}"
  clean_runtime_state "${key}" "${workdir}"
  log "profile ${key} rep=${rep} cores=${cores}"
  set +e
  (
    cd "${workdir}"
    if [[ "${RUN_TO_COMPLETION}" == "1" ]]; then
      /usr/bin/time -f '%e' \
        taskset -c "${cores}" "${PERF_BIN}" record -e "${L2_RECORD_EVENT}" -b -c "${SAMPLE_PERIOD}" -o "${data_file}" -- \
          bash -lc "${command}"
    else
      /usr/bin/time -f '%e' \
        taskset -c "${cores}" "${PERF_BIN}" record -e "${L2_RECORD_EVENT}" -b -c "${SAMPLE_PERIOD}" -o "${data_file}" -- \
          timeout "${TIMEOUT_SECONDS}s" bash -lc "${command}"
    fi
  ) > "${record_log}" 2>&1 &
  local root_pid=$!
  start_pinner "${root_pid}" "${cores}" "${pin_log}"
  pinner_pid="${PINNER_PID}"
  wait "${root_pid}"
  rc=$?
  kill "${pinner_pid}" >/dev/null 2>&1 || true
  wait "${pinner_pid}" >/dev/null 2>&1 || true
  set -e
  if [[ ! -s "${data_file}" ]]; then
    csv_append "${PROFILE_CSV}" "${key}" "${rep}" "fail" "${trace_dir}" "" "" "" "" "" "${record_log}"
    log "profile fail ${key} rep=${rep}"
    return 1
  fi
  "${PROFILING_DIR}/analyze_pebs_trace.sh" \
    --data "${data_file}" \
    --out-dir "${trace_dir}" \
    --event-label "${L2_RECORD_EVENT}" \
    --binary "${exe}" \
    --perf-bin "${PERF_BIN}" > "${analyze_log}" 2>&1 || true
  summary="${trace_dir}/trace_summary.md"
  read -r samples top_branch top_branch_pct top_target top_target_pct < <(python3 - "${summary}" <<'PY'
import re, sys
text = open(sys.argv[1], errors="replace").read() if sys.argv[1] else ""
def m(p):
    x = re.search(p, text)
    return x.groups() if x else ("", "")
samples = re.search(r"LBR samples parsed \(raw\):\s*([0-9]+)", text)
bt = re.search(r"Top branch type:\s*`([^`]+)` \(([0-9.]+)%\)", text)
tt = re.search(r"Top miss target function:\s*`([^`]+)` \(([0-9.]+)%\)", text)
print(
    (samples.group(1) if samples else ""),
    (bt.group(1) if bt else ""),
    (bt.group(2) if bt else ""),
    (tt.group(1).replace(" ", "_") if tt else ""),
    (tt.group(2) if tt else ""),
)
PY
)
  csv_append "${PROFILE_CSV}" "${key}" "${rep}" "ok" "${trace_dir}" "${samples}" "${top_branch}" "${top_branch_pct}" "${top_target}" "${top_target_pct}" "${record_log}"
  rm -f "${data_file}"
}

generate_plans() {
  local bench="$1"
  local work="$2"
  local exe="$3"
  local key traces args cov plan_dir plan log_file status stats
  key="$(bench_key "${bench}")"
  traces=()
  for rep in $(seq 1 "${PROFILE_REPS}"); do
    if [[ -f "${PROFILE_SOURCE_OUT}/profiles/${key}/rep${rep}/l2_miss/lbr_symbolic_dump.txt" ]]; then
      traces+=("${PROFILE_SOURCE_OUT}/profiles/${key}/rep${rep}/l2_miss")
    fi
  done
  if [[ "${#traces[@]}" -eq 0 ]]; then
    while IFS= read -r trace; do
      traces+=("${trace}")
    done < <(find "${PROFILE_SOURCE_OUT}/profiles/${key}" -path '*/l2_miss/lbr_symbolic_dump.txt' -printf '%h\n' 2>/dev/null | sort)
  fi
  if [[ "${#traces[@]}" -eq 0 ]]; then
    for cov in ${COVERAGES}; do
      csv_append "${PLAN_CSV}" "${key}" "${cov}" "fail" "" "" "" "" "" "no profile traces"
    done
    return 1
  fi
  args=()
  for trace in "${traces[@]}"; do
    args+=(--trace-dir "${trace}")
  done
  for cov in ${COVERAGES}; do
    plan_dir="${OUT_DIR}/plans/${key}/cov${cov}"
    plan="${plan_dir}/prefetcht1.plan.json"
    log_file="${plan_dir}/plan.log"
    mkdir -p "${plan_dir}"
    log "plan ${key} cov=${cov} traces=${#traces[@]}"
    set +e
    python3 "${LLVM_PREFETCH_DIR}/tools/prefetchit_trace_to_plan.py" \
      "${args[@]}" \
      --binary "${exe}" \
      --output "${plan}" \
      --summary-dir "${plan_dir}" \
      --top-k 999999 \
      --target-coverage-pct "${cov}" \
      --depth 24 \
      --depth-min 4 \
      --site-budget-per-target 8 \
      --candidate-pool 0 \
      --selection-mode top-sites \
      --prefetch-byte-offsets "${PREFETCH_BYTE_OFFSETS}" \
      --prefetch-mnemonic prefetcht1 \
      --allow-unresolved-targets \
      --addr2line "${ADDR2LINE_BIN}" \
      --nm "${NM_BIN}" > "${log_file}" 2>&1
    rc=$?
    set -e
    if [[ "${rc}" -ne 0 || ! -s "${plan}" ]]; then
      csv_append "${PLAN_CSV}" "${key}" "${cov}" "fail" "${plan}" "" "" "" "" "${log_file}"
      continue
    fi
    stats="$(python3 - "${plan}" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
s = p.get("stats", {})
print(",".join(str(s.get(k, "")) for k in ["selected_injections", "selected_targets", "parsed_samples", "planned_prefetches"]))
PY
)"
    IFS=',' read -r inj targets parsed prefetches <<< "${stats}"
    csv_append "${PLAN_CSV}" "${key}" "${cov}" "ok" "${plan}" "${inj}" "${targets}" "${parsed}" "${prefetches}" "${log_file}"
  done
}

clean_runtime_state() {
  local bench="$1"
  local workdir="$2"
  case "${bench}" in
    shore)
      rm -f \
        "${workdir}/scratch" \
        "${workdir}/log" \
        "${workdir}/diskrw" \
        "${workdir}/db-tpcc-1" \
        "${workdir}/cmdfile" \
        "${workdir}/shore.conf" \
        "${workdir}/info"
      ;;
  esac
  rm -f "${workdir}/lats.bin"
}

eval_variant() {
  local bench="$1"
  local label="$2"
  local work="$3"
  local key src_name command cores
  key="$(bench_key "${bench}")"
  src_name="$(bench_src_name "${bench}")"
  command="$(bench_cmd "${key}")"
  cores="$(bench_core_range "${key}")"
  clean_runtime_state "${key}" "${work}/tailbench/${src_name}"
  OUT_DIR="${EVAL_DIR}" APPEND=1 TIMEOUT_SECONDS="${TIMEOUT_SECONDS}" RUN_TO_COMPLETION="${RUN_TO_COMPLETION}" \
    MEASURED_REQS="$(bench_measured_reqs "${key}")" CONFIG_QPS="$(bench_qps "${key}")" \
    CORE="${cores}" PIN_THREADS=1 \
    L2_EVENT="${L2_STAT_EVENT}" BENCHMARKS=custom \
    CUSTOM_NAME="${key}_${label}" CUSTOM_WORKDIR="${work}/tailbench/${src_name}" CUSTOM_CMD="${command}" \
    bash "${LLVM_PREFETCH_DIR}/scripts/run_workload_l2_screen.sh"
}

summarize() {
  python3 - "${OUT_DIR}" "${SUMMARY_MD}" <<'PY'
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

out = Path(sys.argv[1])
summary = Path(sys.argv[2])

def rows(path):
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))

build = rows(out / "build.csv")
profiles = rows(out / "profiles.csv")
plans = rows(out / "plans.csv")
evals = rows(out / "eval_runs" / "runs.csv")

def fnum(x):
    try:
        return float(x)
    except Exception:
        return float("nan")

profile_type = []
for bench_dir in sorted((out / "profiles").glob("*")):
    if not bench_dir.is_dir():
        continue
    c = Counter()
    for p in bench_dir.glob("rep*/l2_miss/branch_type_distribution.csv"):
        with p.open(newline="") as f:
            for r in csv.DictReader(f):
                c[r["branch_type"]] += int(float(r["count"]))
    total = sum(c.values())
    if total:
        profile_type.append((bench_dir.name, total, {k: 100.0*v/total for k, v in sorted(c.items())}))

site_type = []
for plan_dir in sorted((out / "plans").glob("*")):
    if not plan_dir.is_dir():
        continue
    bench = plan_dir.name
    for cov_dir in sorted(plan_dir.glob("cov*")):
        c = Counter()
        p = cov_dir / "selected_injection_sites.csv"
        if not p.exists():
            continue
        with p.open(newline="") as f:
            for r in csv.DictReader(f):
                c[r["branch_type"]] += 1
        total = sum(c.values())
        if total:
            site_type.append((bench, cov_dir.name.replace("cov", ""), total, {k: 100.0*v/total for k, v in sorted(c.items())}))

baseline = {}
for r in evals:
    name = r.get("benchmark", "")
    if name.endswith("_clangbase"):
        bench = name[:-10]
        baseline[bench] = fnum(r.get("elapsed_s"))

lines = []
lines.append("# TailBench High-MPKI PGO Prefetch")
lines.append("")
lines.append(f"- Result dir: `{out}`")
lines.append(f"- Eval config: same 120s high-MPKI TailBench command as screening.")
lines.append(f"- Profile reps per native workload: `{max([int(r['rep']) for r in profiles if r.get('rep','').isdigit()] or [0])}`")
lines.append("")
lines.append("## Build Status")
lines.append("")
lines.append("| bench | label | status | prefetches | note |")
lines.append("|---|---|---|---:|---|")
for r in build:
    note = (r.get("note") or "").replace("|", "/")[:140]
    lines.append(f"| {r.get('benchmark','')} | {r.get('label','')} | {r.get('status','')} | {r.get('prefetch_count','')} | {note} |")
lines.append("")
lines.append("## Profile Target Branch Type")
lines.append("")
lines.append("| bench | samples | COND | CALL | RET | IND | IND_CALL | UNCOND |")
lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
for bench, total, pct in profile_type:
    lines.append("| {} | {} | {:.1f}% | {:.1f}% | {:.1f}% | {:.1f}% | {:.1f}% | {:.1f}% |".format(
        bench, total, pct.get("COND",0), pct.get("CALL",0), pct.get("RET",0),
        pct.get("IND",0), pct.get("IND_CALL",0), pct.get("UNCOND",0)))
lines.append("")
lines.append("## Plan Summary")
lines.append("")
lines.append("| bench | cov | status | targets | injections | parsed samples | planned prefetches |")
lines.append("|---|---:|---|---:|---:|---:|---:|")
for r in plans:
    lines.append(f"| {r.get('benchmark','')} | {r.get('coverage','')} | {r.get('status','')} | {r.get('selected_targets','')} | {r.get('injections','')} | {r.get('parsed_samples','')} | {r.get('prefetches','')} |")
lines.append("")
lines.append("## Injection Site Type")
lines.append("")
lines.append("| bench | cov | sites | COND | CALL | RET | IND | IND_CALL | UNCOND |")
lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
for bench, cov, total, pct in site_type:
    lines.append("| {} | {} | {} | {:.1f}% | {:.1f}% | {:.1f}% | {:.1f}% | {:.1f}% | {:.1f}% |".format(
        bench, cov, total, pct.get("COND",0), pct.get("CALL",0), pct.get("RET",0),
        pct.get("IND",0), pct.get("IND_CALL",0), pct.get("UNCOND",0)))
lines.append("")
lines.append("## 120s Evaluation")
lines.append("")
lines.append("| bench | label | status | elapsed s | speedup | L2I MPKI | IPC | threads | CPUs | migrations |")
lines.append("|---|---|---|---:|---:|---:|---:|---:|---|---:|")
for r in evals:
    name = r.get("benchmark","")
    m = re.match(r"(.+)_(clangbase|cov[0-9]+)$", name)
    if not m:
        continue
    bench, label = m.groups()
    elapsed = fnum(r.get("elapsed_s"))
    base = baseline.get(bench, float("nan"))
    speedup = base / elapsed if base and elapsed and not math.isnan(base) and not math.isnan(elapsed) else float("nan")
    lines.append("| {} | {} | {} | {:.3f} | {} | {:.3f} | {:.3f} | {} | {} | {} |".format(
        bench, label, r.get("status",""), elapsed,
        f"{speedup:.6f}" if not math.isnan(speedup) else "",
        fnum(r.get("l2i_mpki")), fnum(r.get("ipc")),
        r.get("observed_threads_max",""), r.get("observed_unique_psrs",""),
        r.get("cpu_migrations","")))

summary.write_text("\n".join(lines) + "\n")
PY
}

main() {
  log "out=${OUT_DIR}"
  log "work=${WORK_ROOT}"
  log "benchmarks=${BENCHMARKS}"
  if [[ "${RUN_TO_COMPLETION}" == "1" ]]; then
    log "coverage=${COVERAGES} reps=${PROFILE_REPS} run-to-completion request_seconds=${REQUEST_SECONDS} sample_period=${SAMPLE_PERIOD}"
  else
    log "coverage=${COVERAGES} reps=${PROFILE_REPS} timeout=${TIMEOUT_SECONDS}s sample_period=${SAMPLE_PERIOD}"
  fi

  for bench in ${BENCHMARKS}; do
    key="$(bench_key "${bench}")"
    if [[ "${key}" == "specjbb" ]]; then
      log "specjbb: JVM workload; keeping stat/profile out of LLVM injection build loop"
      continue
    fi

    if ! build_one "${key}" "clangbase" ""; then
      summarize
      continue
    fi
    base_work="${WORK_ROOT}/${key}_clangbase"
    base_exe="${base_work}/tailbench/$(bench_exe_rel "${key}")"

    for rep in $(seq 1 "${PROFILE_REPS}"); do
      profile_one_rep "${key}" "${rep}" "${base_work}" "${base_exe}" || true
    done
    generate_plans "${key}" "${base_work}" "${base_exe}" || true

    if [[ "${SKIP_EVAL}" != "1" ]]; then
      eval_variant "${key}" "clangbase" "${base_work}" || true
    fi

    for cov in ${COVERAGES}; do
      plan="${OUT_DIR}/plans/${key}/cov${cov}/prefetcht1.plan.json"
      if [[ ! -s "${plan}" ]]; then
        continue
      fi
      if build_one "${key}" "cov${cov}" "${plan}"; then
        if [[ "${SKIP_EVAL}" != "1" ]]; then
          eval_variant "${key}" "cov${cov}" "${WORK_ROOT}/${key}_cov${cov}" || true
        fi
      fi
      summarize
    done
    summarize
  done

  if [[ "${BENCHMARKS}" == *specjbb* ]]; then
    log "stat specjbb high-MPKI config"
    OUT_DIR="${EVAL_DIR}" APPEND=1 TIMEOUT_SECONDS="${TIMEOUT_SECONDS}" RUN_TO_COMPLETION="${RUN_TO_COMPLETION}" \
      MEASURED_REQS="$(bench_measured_reqs specjbb)" CONFIG_QPS="$(bench_qps specjbb)" \
      CORE="$(bench_core_range specjbb)" PIN_THREADS=1 \
      L2_EVENT="${L2_STAT_EVENT}" BENCHMARKS=custom \
      CUSTOM_NAME="specjbb_jvm_noinject" CUSTOM_WORKDIR="${TAILBENCH_SRC}/specjbb" CUSTOM_CMD="$(bench_cmd specjbb)" \
      bash "${LLVM_PREFETCH_DIR}/scripts/run_workload_l2_screen.sh" || true
  fi
  summarize
  log "done summary=${SUMMARY_MD}"
}

if [[ "${PREFETCHIT_SOURCE_ONLY:-0}" != "1" ]]; then
  main "$@"
fi
