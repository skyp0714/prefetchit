#!/usr/bin/env bash
# Interleaved A/B of arcilator DualMegaBoom variants (same-binary NOP twins), frozen platform.
#   VARIANTS="seq_d4096_k40 ..." REPS=3 CYCLES=20000 CORE=40 ./measure_arc_variants.sh out.csv
set -euo pipefail
cd "$(dirname "$0")"
OUT="${1:?csv}"; VARIANTS="${VARIANTS:?}"; REPS="${REPS:-3}"; CYCLES="${CYCLES:-20000}"; CORE="${CORE:-40}"
EVENT='cpu/event=0x24,umask=0x24,name=L2I_CODE_RD_MISS/u'
[[ -s "$OUT" ]] || echo "variant,rep,elapsed_sec,instructions,cycles,l2i_misses,l2i_mpki,ipc" > "$OUT"
run() { local v="$1" rep="$2" bin="$3" pcsv=/tmp/arc_perf_$$.csv
  grep -q "^$v,$rep," "$OUT" && return 0
  local s e; s=$(date +%s.%N); taskset -c "$CORE" perf stat -x, -o "$pcsv" -e instructions,cycles,"$EVENT" -- "./$bin" "$CYCLES" > /dev/null; e=$(date +%s.%N)
  python3 - "$OUT" "$v" "$rep" "$s" "$e" "$pcsv" <<'PY'
import csv, sys
out, v, rep, s, e, p = sys.argv[1:]
ev = {}
for row in csv.reader(open(p)):
    if len(row) >= 3:
        try: ev[row[2]] = float(row[0])
        except ValueError: pass
ins, cyc, miss = ev.get("instructions", 0), ev.get("cycles", 0), ev.get("L2I_CODE_RD_MISS", 0)
el = float(e) - float(s)
with open(out, "a", newline="") as f:
    csv.writer(f).writerow([v, rep, f"{el:.3f}", int(ins), int(cyc), int(miss), f"{1000*miss/ins if ins else 0:.3f}", f"{ins/cyc if cyc else 0:.3f}"])
print(f"{v} rep{rep}: {el:.2f}s MPKI={1000*miss/ins:.1f} IPC={ins/cyc:.3f}")
PY
}
for rep in $(seq 1 "$REPS"); do
  run base "$rep" dmb2_base
  for v in $VARIANTS; do run "$v" "$rep" "dmb2_$v"; run "${v}_nop" "$rep" "dmb2_${v}_nop"; done
done
python3 - "$OUT" <<'PY'
import csv, statistics as st, sys
from collections import defaultdict
g = defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])): g[r["variant"]].append(r)
med = {v: st.median(float(r["elapsed_sec"]) for r in rs) for v, rs in g.items()}
mpki = {v: st.mean(float(r["l2i_mpki"]) for r in rs) for v, rs in g.items()}
ins = {v: st.mean(float(r["instructions"]) for r in rs) for v, rs in g.items()}
print("| variant | n | median s | vs base | vs NOP twin | L2I MPKI | instr vs base |\n|---|---:|---:|---:|---:|---:|---:|")
for v in sorted(g, key=lambda x: med[x]):
    t = v + "_nop"
    print(f"| {v} | {len(g[v])} | {med[v]:.2f} | {med['base']/med[v]:.4f}x | {(med[t]/med[v]) if t in med else 0:.4f}x | {mpki[v]:.1f} | {ins[v]/ins['base']-1:+.2%} |")
PY
