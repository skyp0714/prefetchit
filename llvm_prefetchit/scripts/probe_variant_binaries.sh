#!/usr/bin/env bash
# Probe every prebuilt variant binary from the June autotune campaigns at the
# current (frozen) platform config: 1 short fixed-work run each, ranked CSV.
# Usage: OUT=... [MAX_CYCLES=150000] [CORE=5] bash probe_variant_binaries.sh
set -euo pipefail

ROOT=/home/hnpark2/prefetchit
OUT="${OUT:?set OUT}"
RV="${RV:-${ROOT}/benchmarks/tools/rocket-tools/riscv/riscv64-unknown-elf/share/riscv-tests/benchmarks}"
MAX_CYCLES="${MAX_CYCLES:-150000}"
CORE="${CORE:-5}"
PAYLOAD="${PAYLOAD:-qsort}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'

BASE_BIN="${ROOT}/benchmarks/chipyard/sims/verilator/simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig"
# Every June-era runs/ dir holding prebuilt variant binaries (<runs>/<variant>/bin/*):
# COND autotune + PGO-COND compare + the RET-prefetch campaigns.
RUNS_DIRS="${RUNS_DIRS:-\
${ROOT}/llvm_prefetchit/results/static_cond_autotune/static_cond_autotune_20260628_212242/runs \
${ROOT}/llvm_prefetchit/results/cond_sampleip_compare/cond_sampleip_compare_20260628_014845/runs \
${ROOT}/static_return_prefetch/results/static_speedup_eval/runs \
${ROOT}/static_return_prefetch/results/ret_cost_v2_runtime/ret_cost_v2_static_reuse_20260627_012944/runs \
${ROOT}/static_return_prefetch/results/ret_static_vs_pgo_limit/ret_static_vs_pgo_20260626_090419/runs}"

mkdir -p "${OUT}"
CSV="${OUT}/probe.csv"
if [[ ! -s "${CSV}" ]]; then
  printf 'variant,elapsed_sec,instructions,cycles,l2i_misses,l2i_mpki,ipc,ghz,status\n' > "${CSV}"
fi

run_one() {
  local variant="$1" bin="$2"
  grep -q "^${variant}," "${CSV}" && { echo "[skip] ${variant} already probed"; return; }
  local dir="${OUT}/${variant}"
  mkdir -p "${dir}"
  local start end elapsed status=ok
  start="$(date +%s.%N)"
  set +e
  taskset -c "${CORE}" perf stat -x, -o "${dir}/perf.csv" \
    -e instructions,cycles,"${EVENT}" -- \
    "${bin}" "${RV}/${PAYLOAD}.riscv" "+max-cycles=${MAX_CYCLES}" \
    > "${dir}/sim.log" 2>&1
  local rc="$?"
  set -e
  end="$(date +%s.%N)"
  elapsed="$(python3 -c "print(f'{${end}-${start}:.3f}')")"
  if ((rc != 0)) && ! grep -q 'timeout' "${dir}/sim.log"; then
    status="error_rc${rc}"
  fi
  python3 - "$CSV" "$variant" "$elapsed" "$dir/perf.csv" "$status" <<'PY'
import csv, sys
out, variant, elapsed, perf_path, status = sys.argv[1:]
ev = {}
for row in csv.reader(open(perf_path)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
ins = ev.get("instructions", 0.0); cyc = ev.get("cycles", 0.0)
miss = ev.get("L2I_CODE_RD_MISS", 0.0)
el = float(elapsed)
with open(out, "a", newline="") as f:
    csv.writer(f).writerow([variant, elapsed, int(ins), int(cyc), int(miss),
                            f"{1000*miss/ins if ins else 0:.4f}",
                            f"{ins/cyc if cyc else 0:.4f}",
                            f"{cyc/el/1e9 if el else 0:.4f}", status])
PY
  echo "[done] ${variant} ${elapsed}s status=${status}"
}

run_one base "${BASE_BIN}"
for runs in ${RUNS_DIRS}; do
  for d in "${runs}"/*/bin; do
    [[ -d "${d}" ]] || continue
    variant="$(basename "$(dirname "${d}")")"
    [[ "${variant}" == latest ]] && continue
    bin="$(find "${d}" -maxdepth 1 -type f -executable | head -1)"
    [[ -n "${bin}" ]] && run_one "${variant}" "${bin}"
  done
done

python3 - "${CSV}" <<'PY'
import csv, sys
rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["status"] == "ok"]
base = next((r for r in rows if r["variant"] == "base"), None)
if base:
    bt = float(base["elapsed_sec"])
    rows.sort(key=lambda r: float(r["elapsed_sec"]))
    print(f'{"variant":<32} {"time_s":>8} {"vs_base":>8} {"mpki":>8} {"ghz":>6}')
    for r in rows:
        print(f'{r["variant"]:<32} {float(r["elapsed_sec"]):>8.2f} '
              f'{bt/float(r["elapsed_sec"]):>7.3f}x {float(r["l2i_mpki"]):>8.3f} '
              f'{float(r["ghz"]):>6.3f}')
PY
