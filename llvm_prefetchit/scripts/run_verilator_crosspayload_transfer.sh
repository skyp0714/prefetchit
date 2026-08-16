#!/usr/bin/env bash
# Cross-payload transfer test: do the qsort-tuned static (fetch-gap 100k) and
# qsort-profiled PGO (cond cov50) simulator binaries still beat baseline when
# the simulator runs other RISC-V payloads? Fixed work via +max-cycles.
set -euo pipefail

ROOT=/home/hnpark2/prefetchit
OUT="${OUT:-${ROOT}/llvm_prefetchit/results/paper_goal_20260815/verilator_crosspayload}"
RV="${RV:-${ROOT}/benchmarks/tools/rocket-tools/riscv/riscv64-unknown-elf/share/riscv-tests/benchmarks}"
MAX_CYCLES="${MAX_CYCLES:-150000}"
REPS="${REPS:-3}"
CORE="${CORE:-5}"
PAYLOADS="${PAYLOADS:-mm dhrystone median qsort}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'

BASE_BIN="${BASE_BIN:-${ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig}"
STATIC_BIN="${STATIC_BIN:-${ROOT}/llvm_prefetchit/results/static_cond_autotune/static_cond_autotune_20260628_212242/runs/static_gap100k_cur0_skip/bin/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig-llvm-static_gap100k_cur0_skip}"
PGO_BIN="${PGO_BIN:-${ROOT}/llvm_prefetchit/results/cond_sampleip_compare/cond_sampleip_compare_20260628_014845/runs/pgo_cond_cov50/bin/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig-llvm-pgo_cond_cov50}"

[[ -x "${BASE_BIN}" && -x "${STATIC_BIN}" && -x "${PGO_BIN}" ]]
mkdir -p "${OUT}"
CSV="${OUT}/runs.csv"
if [[ ! -s "${CSV}" ]]; then
  printf 'payload,variant,rep,elapsed_sec,instructions,cycles,l2i_misses,l2i_mpki,ipc,status\n' > "${CSV}"
fi

run_one() {
  local payload="$1" variant="$2" rep="$3" bin="$4"
  local dir="${OUT}/${payload}/${variant}_rep${rep}"
  mkdir -p "${dir}"
  local start end elapsed status=ok
  start="$(date +%s.%N)"
  set +e
  taskset -c "${CORE}" perf stat -x, -o "${dir}/perf.csv" \
    -e instructions,cycles,"${EVENT}" -- \
    "${bin}" "${RV}/${payload}.riscv" "+max-cycles=${MAX_CYCLES}" \
    > "${dir}/sim.log" 2>&1
  local rc="$?"
  set -e
  end="$(date +%s.%N)"
  elapsed="$(python3 -c "print(f'{${end}-${start}:.3f}')")"
  # max-cycles cap exits nonzero with '*** FAILED *** (timeout)'; that IS the
  # fixed-work case. Anything else is a real failure.
  if ((rc != 0)) && ! grep -q 'timeout' "${dir}/sim.log"; then
    status="error_rc${rc}"
  fi
  python3 - "$CSV" "$payload" "$variant" "$rep" "$elapsed" "$dir/perf.csv" "$status" <<'PY'
import csv, sys
out, payload, variant, rep, elapsed, perf_path, status = sys.argv[1:]
ev = {}
for row in csv.reader(open(perf_path)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
ins = ev.get("instructions", 0.0); cyc = ev.get("cycles", 0.0)
miss = ev.get("L2I_CODE_RD_MISS", 0.0)
mpki = 1000*miss/ins if ins else 0.0
ipc = ins/cyc if cyc else 0.0
with open(out, "a", newline="") as f:
    csv.writer(f).writerow([payload, variant, rep, elapsed,
                            int(ins), int(cyc), int(miss),
                            f"{mpki:.4f}", f"{ipc:.4f}", status])
PY
  echo "[done] ${payload} ${variant} rep${rep} ${elapsed}s status=${status}"
}

for rep in $(seq 1 "${REPS}"); do
  for payload in ${PAYLOADS}; do
    for spec in "base:${BASE_BIN}" "static:${STATIC_BIN}" "pgo:${PGO_BIN}"; do
      run_one "${payload}" "${spec%%:*}" "${rep}" "${spec#*:}"
    done
  done
done

python3 - "${CSV}" <<'PY'
import csv, statistics as st, sys
from collections import defaultdict
rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["status"] == "ok" or "timeout" not in r["status"]]
groups = defaultdict(list)
for r in rows:
    groups[(r["payload"], r["variant"])].append(r)
print(f'{"payload":<10} {"variant":<7} {"n":>2} {"time_s":>9} {"mpki":>8} {"vs_base":>8}')
base_mean = {}
for (p, v), rs in sorted(groups.items()):
    t = st.mean(float(r["elapsed_sec"]) for r in rs)
    if v == "base": base_mean[p] = t
for (p, v), rs in sorted(groups.items()):
    t = st.mean(float(r["elapsed_sec"]) for r in rs)
    m = st.mean(float(r["l2i_mpki"]) for r in rs)
    sp = base_mean.get(p, t)/t if base_mean.get(p) else 0
    print(f'{p:<10} {v:<7} {len(rs):>2} {t:>9.2f} {m:>8.3f} {sp:>7.3f}x')
PY
