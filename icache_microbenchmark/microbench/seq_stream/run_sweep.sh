#!/usr/bin/env bash
# Sweep lookahead distance D and spacing S for the sequential code-stream microbench.
#   CORE=70 REPS=10 CODE_MB=16 ./run_sweep.sh out.csv
set -euo pipefail
OUTCSV="${1:?csv}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="${CORE:-70}"; REPS="${REPS:-10}"; CODE_MB="${CODE_MB:-16}"
DISTANCES="${DISTANCES:-256 512 1024 2048 4096 8192}"
SPACINGS="${SPACINGS:-64 128 256}"
LINES="${LINES:-1}"
BUILD="${HERE}/build"; mkdir -p "${BUILD}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'
[[ -s "${OUTCSV}" ]] || echo "variant,distance,spacing,lines,code_mb,reps,sec_per_rep,instructions,cycles,l2i_misses,l2i_mpki,ipc" > "${OUTCSV}"
build() { # name, gen-args...
  local name="$1"; shift
  [[ -x "${BUILD}/${name}" ]] && return
  python3 "${HERE}/gen_seq_stream.py" --code-mb "${CODE_MB}" --out "${BUILD}/${name}.s" "$@" >/dev/null
  clang-19 -O1 -o "${BUILD}/${name}" "${HERE}/main.c" "${BUILD}/${name}.s"
  rm -f "${BUILD}/${name}.s"
}
run() { # name distance spacing lines
  local name="$1" d="$2" s="$3" l="$4"
  local perf="${BUILD}/${name}.perf.csv"
  taskset -c "${CORE}" perf stat -x, -o "${perf}" -e instructions,cycles,"${EVENT}" -- "${BUILD}/${name}" "${REPS}" > "${BUILD}/${name}.out"
  python3 - "${OUTCSV}" "${name}" "$d" "$s" "$l" "${CODE_MB}" "${REPS}" "${BUILD}/${name}.out" "${perf}" <<'PY'
import csv, re, sys
out, name, d, s, l, mb, reps, res, perf = sys.argv[1:]
spr = float(re.search(r"sec_per_rep=([0-9.]+)", open(res).read()).group(1))
ev = {}
for row in csv.reader(open(perf)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
ins, cyc, miss = ev.get("instructions", 0), ev.get("cycles", 0), ev.get("L2I_CODE_RD_MISS", 0)
with open(out, "a", newline="") as f:
    csv.writer(f).writerow([name, d, s, l, mb, reps, f"{spr:.5f}", int(ins), int(cyc), int(miss), f"{1000*miss/ins if ins else 0:.3f}", f"{ins/cyc if cyc else 0:.3f}"])
print(f"{name:28s} sec/rep={spr:.4f} MPKI={1000*miss/ins:.2f} IPC={ins/cyc:.3f}")
PY
}
build base --distance 0
run base 0 0 0
for s in ${SPACINGS}; do
  build "nop_s${s}" --distance 1024 --spacing "${s}" --lines "${LINES}" --nop
  run "nop_s${s}" 0 "${s}" "${LINES}"
  for d in ${DISTANCES}; do
    build "pf_d${d}_s${s}" --distance "${d}" --spacing "${s}" --lines "${LINES}"
    run "pf_d${d}_s${s}" "${d}" "${s}" "${LINES}"
  done
done
