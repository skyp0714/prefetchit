#!/usr/bin/env bash
# Fix-up queue after the first 20260815 campaign attempt:
# the postgres static plans were generated against the stripped install_base
# binary (addr2line -> line 0 -> pass skips all sites). Regenerate against a
# freshly built debug backend binary, rebuild variants, and run the paired
# evals that were skipped. Also runs the PGO reference arm and gem5 screen.
set -uo pipefail

ROOT="${PREFETCHIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LLVM="${ROOT}/llvm_prefetchit"
OUT="${LLVM}/results/paper_goal_20260815"
PLANS="${OUT}/postgresql_static/plans_v2"
BUILD_ROOT="${LLVM}/work/pgo_goal_20260713/bins/postgresql_simple_c8_tune1/build"
SRC="${BUILD_ROOT}/src"
LOG="${OUT}/campaign.log"
PLANNER="${ROOT}/static_return_prefetch/tools/static_branch_target_plan.py"

log() { printf '[%(%F %T)T] %s\n' -1 "$*" | tee -a "${LOG}"; }

# ---- stage A: wait for the (orphaned) verilator campaign to finish ----------
log "fixup stageA: waiting for verilator cross-payload to finish"
CSV="${OUT}/verilator_crosspayload/runs.csv"
for _ in $(seq 1 480); do
  pgrep -f run_verilator_crosspayload_transfer >/dev/null || break
  sleep 60
done
log "fixup stageA: verilator done, rows=$(($(wc -l < "${CSV}" 2>/dev/null || echo 1) - 1))"

# ---- stage B: rebuild baseline backend with debug info ----------------------
log "fixup stageB: rebuilding baseline debug backend binary"
make -C "${SRC}/src/backend" clean > "${OUT}/postgresql_static/baseline_rebuild.log" 2>&1
make -C "${SRC}/src/backend" generated-headers >> "${OUT}/postgresql_static/baseline_rebuild.log" 2>&1
rm -f "${SRC}"/src/common/*_srv.o "${SRC}/src/common/libpgcommon_srv.a"
rm -f "${SRC}"/src/port/*_srv.o "${SRC}/src/port/libpgport_srv.a"
make -C "${SRC}/src/common" -j24 libpgcommon_srv.a >> "${OUT}/postgresql_static/baseline_rebuild.log" 2>&1
make -C "${SRC}/src/port" -j24 libpgport_srv.a >> "${OUT}/postgresql_static/baseline_rebuild.log" 2>&1
make -C "${SRC}/src/backend" -j24 postgres >> "${OUT}/postgresql_static/baseline_rebuild.log" 2>&1
DEBUG_BIN="${OUT}/postgresql_static/postgres.baseline.debug"
cp -p "${SRC}/src/backend/postgres" "${DEBUG_BIN}"
if ! readelf -S "${DEBUG_BIN}" | grep -q debug_line; then
  log "fixup stageB: ERROR baseline binary has no debug_line; aborting plan regen"
  exit 1
fi
log "fixup stageB: debug baseline at ${DEBUG_BIN}"

# ---- stage C: regenerate static plans against the debug binary --------------
log "fixup stageC: regenerating static plans (4 parallel)"
mkdir -p "${PLANS}"
gen() {
  local label="$1" topf="$2" maxinj="$3"
  python3 "${PLANNER}" \
    --binary "${DEBUG_BIN}" \
    --output "${PLANS}/${label}/prefetchit.plan.json" \
    --label "${label}" \
    --prefetch-mnemonic prefetcht1 --prefetch-byte-offsets 0 \
    --top-functions 0 --min-function-size 16 \
    --branch-types CALL,COND,RET,UNCOND --target-modes body \
    --site-depth 8 \
    --max-injections "${maxinj}" \
    --max-injections-per-target-function 16 \
    --max-injections-per-target-cacheline 1 \
    --body-target-functions "${topf}" \
    --body-cachelines-per-function 64 --min-body-target-size 16 \
    --rank-by structural-hotpath --skip-same-cacheline --pretty \
    > "${PLANS}/${label}.log" 2>&1
  log "fixup stageC: ${label} rc=$? inj=$(jq -r '.stats.selected_injections' "${PLANS}/${label}/prefetchit.plan.json" 2>/dev/null)"
}
gen pg_body_top8_b84_d8_o0 8 84 &
gen pg_body_top16_b168_d8_o0 16 168 &
gen pg_body_top32_b336_d8_o0 32 336 &
gen pg_body_top64_b672_d8_o0 64 672 &
wait

# sanity: require nonzero site lines in at least one plan
ok_plans=0
for d in "${PLANS}"/*/; do
  f="${d}/prefetchit.plan.json"
  [[ -s "${f}" ]] || continue
  nz="$(jq '[.injections[].site.line] | map(select(. > 0)) | length' "${f}")"
  log "fixup stageC: $(basename "${d}") nonzero-site-lines=${nz}"
  if [[ "${nz}" -gt 0 ]]; then ok_plans=$((ok_plans + 1)); else rm -rf "${d}"; fi
done
if ((ok_plans == 0)); then
  log "fixup stageC: ERROR all plans still have line=0 sites; stopping before builds"
  exit 1
fi

# ---- stage D: build variants ------------------------------------------------
log "fixup stageD: building static variants"
labels=""
for d in "${PLANS}"/*/; do labels="${labels} $(basename "${d}")"; done
BUILD_VARIANTS="${labels# }" BUILD_ROOT="${BUILD_ROOT}" \
  bash "${LLVM}/scripts/build_postgresql_lbr_pgo_variants.sh" \
    "${PLANS}" "${OUT}/postgresql_static/bins_v2" >> "${LOG}" 2>&1
log "fixup stageD: rc=$?"
cat "${OUT}/postgresql_static/bins_v2/build_summary.csv" >> "${LOG}" 2>/dev/null

# ---- stage E: paired evals --------------------------------------------------
log "fixup stageE: postgres paired evals"
run_pg() {
  local bin="$1" label="$2"
  [[ -x "${bin}" ]] || { log "fixup stageE: missing ${bin}"; return 1; }
  DURATION=30 WARMUP_DURATION=20 QUERY_MODE=simple CLIENTS=8 REPS=5 \
    bash "${LLVM}/scripts/run_final_postgresql_paired.sh" \
      "${bin}" "${OUT}/postgresql_static/paired/${label}" "${label}" \
      >> "${LOG}" 2>&1
  log "fixup stageE: ${label} rc=$? $(jq -c '.speedup' "${OUT}/postgresql_static/paired/${label}/paired_summary.json" 2>/dev/null)"
}
run_pg "${LLVM}/work/pgo_goal_20260713/bins/postgresql_simple_c8_tune1/installs/cov25_d8_32_b1_o0/bin/postgres" \
  "pgo_cov25_d8_32_b1_o0_ref"
for d in "${OUT}/postgresql_static/bins_v2/installs/"*/; do
  label="$(basename "${d}")"
  # skip variants whose binary carries zero prefetches
  n="$(objdump -d "${d}/bin/postgres" 2>/dev/null | grep -c prefetcht1 || true)"
  if [[ "${n:-0}" -eq 0 ]]; then log "fixup stageE: skip ${label} (0 prefetches)"; continue; fi
  run_pg "${d}/bin/postgres" "${label}"
done

# ---- stage F: gem5 screen ---------------------------------------------------
log "fixup stageF: gem5 screen"
GEM5_ROOT="${ROOT}/build/X86"
SE="${ROOT}/benchmarks/gem5/configs/deprecated/example/se.py"
BUSY=/tmp/static_verify/busy_static
for variant in gem5.opt gem5.opt.eventq-prefetch-v1; do
  bin="${GEM5_ROOT}/${variant}"
  [[ -x "${bin}" ]] || continue
  dir="${OUT}/gem5_screen/${variant}"
  mkdir -p "${dir}"
  timeout --signal=INT 200 taskset -c 7 perf stat -x, -o "${dir}/perf.csv" \
    -e instructions,cycles,'cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u' -- \
    "${bin}" --outdir="${dir}/m5out" "${SE}" -c "${BUSY}" \
      --cpu-type=X86O3CPU --caches --l2cache > "${dir}/sim.log" 2>&1
  log "fixup stageF: ${variant} rc=$?"
done
python3 - "${OUT}/gem5_screen" <<'PY' | tee -a "${LOG}"
import csv, pathlib, sys
for perf in sorted(pathlib.Path(sys.argv[1]).glob("*/perf.csv")):
    ev = {}
    for row in csv.reader(perf.open()):
        if len(row) >= 3:
            try: ev[row[2]] = float(row[0])
            except ValueError: pass
    ins = ev.get("instructions", 0); miss = ev.get("L2I_CODE_RD_MISS", 0)
    print(f"gem5-screen {perf.parent.name}: instructions={ins:.3e} "
          f"l2i_mpki={1000*miss/ins if ins else 0:.3f}")
PY

log "fixup campaign complete"
