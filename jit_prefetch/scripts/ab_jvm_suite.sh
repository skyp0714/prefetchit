#!/usr/bin/env bash
# DaCapo / Renaissance A/B on the patched JDK: stock vs C2 prefetch flag sets.
#
# Replaces ab_cassandra.sh, ab_cassandra_cat.sh, ab_cassandra_combo.sh,
# ab_tomcat_cat.sh, ab_chirper.sh and ab_it0.sh (see archive/ for the originals).
#
#   SUITE=dacapo|renaissance BENCH=tomcat CONFIGS="stock=;v4_gated=<flags>" \
#   REPS=5 CORES=8-15 ITERS=25 PERF_DELAY=60 WINDOW_SEC=12 ab_jvm_suite.sh [OUT.csv]
#
# Metric: DaCapo = mean of the last 10 warmup-iteration times (ms) from the log;
# Renaissance = mean of the last 20 iterations from --json. A perf window on
# the java process records L2I MPKI / IPC (and L1I MPKI when L1I=1).
# CORES="" runs unpinned. Run under scripts/platform/freeze_platform.sh, one
# workload at a time.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"

SUITE="${SUITE:-dacapo}"
BENCH="${BENCH:-tomcat}"
OUT="${1:-${JIT_PREFETCH_ROOT}/results/${BENCH}_ab.csv}"
REPS="${REPS:-3}"
CORES="${CORES:-8-15}"
ITERS="${ITERS:-25}"
PERF_DELAY="${PERF_DELAY:-60}"
WINDOW_SEC="${WINDOW_SEC:-12}"
L1I="${L1I:-0}"
JAVA_EXTRA="${JAVA_EXTRA:-}"
GATED="-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32 -XX:PrefetchEntryMinBytecode=256"
CONFIGS="${CONFIGS:-stock=;v4_gated=${GATED}}"
LOG_DIR="${LOG_DIR:-$(dirname "${OUT}")/${BENCH}_logs}"
SCRATCH="${SCRATCH:-/tmp/dcscratch_${BENCH}_$$}"
EVENTS='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/,instructions,cycles'
[[ "${L1I}" == 1 ]] && EVENTS+=',cpu/event=0x80,umask=0x84,name=L1I_MISS/'
mkdir -p "${LOG_DIR}"

[[ -x "${JDK}/bin/java" ]] || { echo "[err] JDK not built: ${JDK}" >&2; exit 1; }
case "${SUITE}" in
  dacapo) [[ -f "${DACAPO}" ]] || { echo "[err] missing ${DACAPO}" >&2; exit 1; } ;;
  renaissance) [[ -f "${REN}" ]] || { echo "[err] missing ${REN}" >&2; exit 1; } ;;
  *) echo "[err] SUITE must be dacapo or renaissance" >&2; exit 2 ;;
esac
# DaCapo cassandra/tomcat need the security manager on JDK 17
[[ "${SUITE}" == dacapo && "${BENCH}" =~ ^(cassandra|tomcat|kafka)$ ]] && JAVA_EXTRA+=" -Djava.security.manager=allow"
PIN=(); [[ -n "${CORES}" ]] && PIN=(taskset -c "${CORES}")

echo "suite,bench,config,rep,steady_ms,l2i_mpki,ipc,l1i_mpki" > "${OUT}"

run_one() {
  local cfg="$1" rep="$2" flags="$3"
  local log="${LOG_DIR}/${cfg}_rep${rep}.log" perf="${LOG_DIR}/${cfg}_rep${rep}.perf.csv"
  local json="${LOG_DIR}/${cfg}_rep${rep}.json"
  rm -f "${perf}"
  # shellcheck disable=SC2086
  if [[ "${SUITE}" == dacapo ]]; then
    "${PIN[@]}" "${JDK}/bin/java" ${JAVA_EXTRA} ${flags} -jar "${DACAPO}" "${BENCH}" \
      -n "${ITERS}" --scratch-directory "${SCRATCH}" > "${log}" 2>&1 &
  else
    "${PIN[@]}" "${JDK}/bin/java" ${JAVA_EXTRA} ${flags} -jar "${REN}" -r "${ITERS}" \
      --json "${json}" "${BENCH}" > "${log}" 2>&1 &
  fi
  local jpid=$!
  sleep "${PERF_DELAY}"
  if kill -0 "${jpid}" 2>/dev/null; then
    perf stat -x, -o "${perf}" -e "${EVENTS}" -p "${jpid}" -- sleep "${WINDOW_SEC}" 2>/dev/null || true
  fi
  wait "${jpid}" || true
  python3 - "${SUITE}" "${BENCH}" "${cfg}" "${rep}" "${log}" "${json}" "${perf}" >> "${OUT}" <<'PY'
import csv, json, re, sys
suite, bench, cfg, rep, log, jsonf, perf = sys.argv[1:]
if suite == 'dacapo':
    v = [int(x) for x in re.findall(r'completed warmup \d+ in (\d+)', open(log).read())][-10:]
    steady = sum(v) / len(v) if v else float('nan')
else:
    try:
        d = json.load(open(jsonf))
        t = [r['duration_ns'] for r in d['data'][bench]['results']][-20:]
        steady = sum(t) / len(t) / 1e6
    except Exception:
        steady = float('nan')
ev = {}
try:
    for row in csv.reader(open(perf)):
        if len(row) >= 3 and row[0] and not row[0].startswith('<'):
            try: ev[row[2]] = float(row[0])
            except ValueError: pass
except FileNotFoundError:
    pass
inst = ev.get('instructions', 0); cyc = ev.get('cycles', 0)
mpki = 1000 * ev.get('L2I_CODE_RD_MISS', 0) / inst if inst else float('nan')
l1 = 1000 * ev.get('L1I_MISS', 0) / inst if inst and 'L1I_MISS' in ev else float('nan')
ipc = inst / cyc if cyc else float('nan')
print(f"{suite},{bench},{cfg},{rep},{steady:.1f},{mpki:.2f},{ipc:.3f},{l1:.2f}")
PY
  tail -1 "${OUT}"
}

for rep in $(seq 1 "${REPS}"); do
  IFS=';' read -ra arms <<< "${CONFIGS}"
  for arm in "${arms[@]}"; do
    run_one "${arm%%=*}" "${rep}" "${arm#*=}"
  done
done
rm -rf "${SCRATCH}"
echo "DONE ${OUT}"
