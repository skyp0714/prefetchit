#!/usr/bin/env bash
# JCodeStream A/B: stock vs HotSpot C2 prefetch flag sets, on the patched JDK.
#
#   ab_jcs.sh [OUT.csv] [REPS] [CLASS]      (defaults: results/jcs_ab.csv, 3, JCS3)
#   CONFIGS="stock=;v4_128x32=-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32"
#   CORE=40 ITERS=300 INNER=10 WINDOW_SEC=10
#
# Each run: fresh JVM pinned to CORE, ITERS iterations of INNER rounds; the
# metric is the mean of the last ITERS/2 iterations (compile queue drains in the
# first half), plus a WINDOW_SEC perf window for L2I MPKI/IPC once steady.
# Baseline flags are the workload definition (pure C2, low threshold) and are
# identical in every arm. Run under scripts/platform/freeze_platform.sh.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/project_env.sh"

OUT="${1:-${JIT_PREFETCH_ROOT}/results/jcs_ab.csv}"
REPS="${2:-3}"
CLASS="${3:-JCS3}"
CORE="${CORE:-40}"
ITERS="${ITERS:-300}"
INNER="${INNER:-10}"
WINDOW_SEC="${WINDOW_SEC:-10}"
CONFIGS="${CONFIGS:-stock=;v4_128x32=-XX:PrefetchEntryAhead=128 -XX:PrefetchEntryLines=32}"
BASE_FLAGS="${BASE_FLAGS:--XX:-TieredCompilation -XX:CompileThreshold=100 -XX:CICompilerCount=16}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/'
LOG_DIR="${LOG_DIR:-$(dirname "${OUT}")/jcs_logs}"
mkdir -p "${LOG_DIR}"

[[ -x "${JDK}/bin/java" ]] || { echo "[err] JDK not built: ${JDK}" >&2; exit 1; }
[[ -f "${JIT_PREFETCH_ROOT}/jcodestream/${CLASS}.class" ]] || { echo "[err] compile jcodestream first (javac *.java)" >&2; exit 1; }

echo "config,rep,iter_ms,mpki,ipc,iters_measured" > "${OUT}"

run_one() {
  local cfg="$1" rep="$2" flags="$3"
  local log="${LOG_DIR}/${cfg}_rep${rep}.log" perf="${LOG_DIR}/${cfg}_rep${rep}.perf.csv"
  # shellcheck disable=SC2086
  taskset -c "${CORE}" "${JDK}/bin/java" ${BASE_FLAGS} ${flags} \
    -cp "${JIT_PREFETCH_ROOT}/jcodestream" "${CLASS}" "${ITERS}" "${INNER}" > "${log}" 2>&1 &
  local jpid=$!
  # wait until the first half is done (steady state), then open the perf window
  local done_iters=0
  until (( done_iters >= ITERS / 2 )); do
    done_iters="$(grep -c '^iter ' "${log}" 2>/dev/null || true)"; done_iters="${done_iters:-0}"
    kill -0 "${jpid}" 2>/dev/null || break
    sleep 0.2
  done
  perf stat -x, -o "${perf}" -e "instructions,cycles,${EVENT}" -p "${jpid}" -- sleep "${WINDOW_SEC}" 2>/dev/null || true
  wait "${jpid}" || true
  python3 - "${cfg}" "${rep}" "${log}" "${perf}" "${ITERS}" >> "${OUT}" <<'PY'
import csv, re, sys
cfg, rep, log, perf, iters = sys.argv[1:]
ms = [int(m.group(1)) for m in re.finditer(r'^iter \d+ ms (\d+)$', open(log).read(), re.M)]
tail = ms[len(ms) // 2:] if ms else []
ev = {}
try:
    for row in csv.reader(open(perf)):
        if len(row) >= 3 and row[0] and not row[0].startswith('<'):
            try: ev[row[2]] = float(row[0])
            except ValueError: pass
except FileNotFoundError:
    pass
inst, cyc, miss = ev.get('instructions', 0), ev.get('cycles', 0), ev.get('L2I_CODE_RD_MISS', 0)
mpki = 1000 * miss / inst if inst else float('nan')
ipc = inst / cyc if cyc else float('nan')
mean = sum(tail) / len(tail) if tail else float('nan')
print(f"{cfg},{rep},{mean:.2f},{mpki:.2f},{ipc:.3f},{len(tail)}")
PY
  tail -1 "${OUT}"
}

for rep in $(seq 1 "${REPS}"); do
  IFS=';' read -ra arms <<< "${CONFIGS}"
  for arm in "${arms[@]}"; do
    run_one "${arm%%=*}" "${rep}" "${arm#*=}"
  done
done
echo "DONE ${OUT}"
